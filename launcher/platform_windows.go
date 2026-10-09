//go:build windows

package main

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	createNoWindow               = 0x08000000
	createNewConsole             = 0x00000010
	jobObjectExtendedLimitInfo   = 9
	jobObjectLimitKillOnJobClose = 0x00002000
	processSetQuota              = 0x0100
	processTerminate             = 0x0001
	mbOK                         = 0x00000000
	mbIconError                  = 0x00000010
	mbIconInformation            = 0x00000040
	mbSetForeground              = 0x00010000
	keyRead                      = 0x20019
	keyQueryValue                = 0x0001
	keySetValue                  = 0x0002
	keyCreateSubKey              = 0x0004
)

// kernel32 and user32 are KnownDLLs, so loading them by name cannot be hijacked.
var (
	kernel32                     = syscall.NewLazyDLL("kernel32.dll")
	user32                       = syscall.NewLazyDLL("user32.dll")
	advapi32                     = syscall.NewLazyDLL("advapi32.dll")
	procRegCreateKeyExW          = advapi32.NewProc("RegCreateKeyExW")
	procRegSetValueExW           = advapi32.NewProc("RegSetValueExW")
	procCreateJobObjectW         = kernel32.NewProc("CreateJobObjectW")
	procSetInformationJobObject  = kernel32.NewProc("SetInformationJobObject")
	procAssignProcessToJobObject = kernel32.NewProc("AssignProcessToJobObject")
	procMessageBoxW              = user32.NewProc("MessageBoxW")
	procCreateMutexW             = kernel32.NewProc("CreateMutexW")
)

const errorAlreadyExists = 183

type ioCounters struct {
	ReadOperationCount, WriteOperationCount, OtherOperationCount uint64
	ReadTransferCount, WriteTransferCount, OtherTransferCount    uint64
}

type jobBasicLimit struct {
	PerProcessUserTimeLimit int64
	PerJobUserTimeLimit     int64
	LimitFlags              uint32
	MinimumWorkingSetSize   uintptr
	MaximumWorkingSetSize   uintptr
	ActiveProcessLimit      uint32
	Affinity                uintptr
	PriorityClass           uint32
	SchedulingClass         uint32
}

// jobExtendedLimit mirrors JOBOBJECT_EXTENDED_LIMIT_INFORMATION.
type jobExtendedLimit struct {
	BasicLimitInformation jobBasicLimit
	IoInfo                ioCounters
	ProcessMemoryLimit    uintptr
	JobMemoryLimit        uintptr
	PeakProcessMemoryUsed uintptr
	PeakJobMemoryUsed     uintptr
}

type osPlatform struct {
	job   syscall.Handle // 0 if the job could not be created
	mutex syscall.Handle // held until the process exits
}

func newPlatform() *osPlatform {
	p := &osPlatform{}
	h, _, _ := procCreateJobObjectW.Call(0, 0)
	if h == 0 {
		return p
	}
	var info jobExtendedLimit
	info.BasicLimitInformation.LimitFlags = jobObjectLimitKillOnJobClose
	r, _, _ := procSetInformationJobObject.Call(h, jobObjectExtendedLimitInfo,
		uintptr(unsafe.Pointer(&info)), unsafe.Sizeof(info))
	if r == 0 {
		syscall.CloseHandle(syscall.Handle(h))
		return p
	}
	p.job = syscall.Handle(h)
	return p
}

// Shutdown closes the job handle; Windows then kills every process in it
// (only the ssh processes this launcher started). The OS does the same if
// the launcher crashes, because the handle closes with the process.
func (p *osPlatform) Shutdown() {
	if p.job != 0 {
		syscall.CloseHandle(p.job)
		p.job = 0
	}
}

func (p *osPlatform) Getenv(k string) string { return os.Getenv(k) }

func (p *osPlatform) Exists(path string) bool {
	st, err := os.Stat(path)
	if err != nil {
		// App execution aliases (e.g. WindowsApps\wt.exe) are reparse points
		// that Stat may not follow; they still start fine.
		st, err = os.Lstat(path)
	}
	return err == nil && !st.IsDir()
}

func (p *osPlatform) LookPath(file string) (string, error) { return exec.LookPath(file) }

func (p *osPlatform) Alert(msg string, isError bool) {
	flags := uintptr(mbOK | mbSetForeground | mbIconInformation)
	if isError {
		flags = mbOK | mbSetForeground | mbIconError
	}
	m, _ := syscall.UTF16PtrFromString(msg)
	t, _ := syscall.UTF16PtrFromString(title)
	procMessageBoxW.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
}

type cmdProc struct{ c *exec.Cmd }

func (c cmdProc) Wait() error { return c.c.Wait() }
func (c cmdProc) Kill() error { return c.c.Process.Kill() }

func (p *osPlatform) StartSSH(path string, args []string, stderr io.Writer) (Proc, error) {
	c := exec.Command(path, args...)
	c.Stderr = stderr
	c.WaitDelay = 2 * time.Second
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
	if err := c.Start(); err != nil {
		return nil, err
	}
	if p.job != 0 {
		h, err := syscall.OpenProcess(processSetQuota|processTerminate, false, uint32(c.Process.Pid))
		if err == nil {
			procAssignProcessToJobObject.Call(uintptr(p.job), uintptr(h))
			syscall.CloseHandle(h)
		}
	}
	return cmdProc{c}, nil
}

func (p *osPlatform) Output(path string, args []string) ([]byte, error) {
	c := exec.Command(path, args...)
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
	c.WaitDelay = 2 * time.Second
	return c.Output()
}

func (p *osPlatform) StartBrowser(path string, args []string) (Proc, error) {
	c := exec.Command(path, args...)
	if err := c.Start(); err != nil {
		return nil, err
	}
	return cmdProc{c}, nil
}

// StartTerminal starts a visible window and lets it go: it is not put in the
// kill-on-close job, so it outlives the launcher.
func (p *osPlatform) StartTerminal(path string, args []string, newConsole bool) error {
	c := exec.Command(path, args...)
	if newConsole {
		c.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNewConsole}
	}
	return startAndRelease(c.Start, func() error { return c.Process.Release() })
}

// registerProtocol writes vals under HKCU, skipping values that already hold
// the same data, so a normal launch leaves the registry alone when nothing changed.
func registerProtocol(vals []regValue) error {
	for _, v := range vals {
		if err := setRegString(v); err != nil {
			return fmt.Errorf(`HKCU\%s [%s]: %v`, v.Key, v.Name, err)
		}
	}
	return nil
}

func setRegString(v regValue) error {
	sub, err := syscall.UTF16PtrFromString(v.Key)
	if err != nil {
		return err
	}
	name, err := syscall.UTF16PtrFromString(v.Name)
	if err != nil {
		return err
	}
	data, err := syscall.UTF16FromString(v.Data)
	if err != nil {
		return err
	}
	var k syscall.Handle
	r, _, _ := procRegCreateKeyExW.Call(uintptr(syscall.HKEY_CURRENT_USER), uintptr(unsafe.Pointer(sub)), 0, 0, 0,
		keyQueryValue|keySetValue|keyCreateSubKey, 0, uintptr(unsafe.Pointer(&k)), 0)
	if r != 0 {
		return syscall.Errno(r)
	}
	defer syscall.RegCloseKey(k)
	buf := make([]uint16, len(data)+16)
	n := uint32(len(buf) * 2)
	var typ uint32
	if syscall.RegQueryValueEx(k, name, nil, &typ, (*byte)(unsafe.Pointer(&buf[0])), &n) == nil &&
		typ == syscall.REG_SZ && syscall.UTF16ToString(buf[:n/2]) == v.Data {
		return nil
	}
	r, _, _ = procRegSetValueExW.Call(uintptr(k), uintptr(unsafe.Pointer(name)), 0, syscall.REG_SZ,
		uintptr(unsafe.Pointer(&data[0])), uintptr(len(data)*2))
	if r != 0 {
		return syscall.Errno(r)
	}
	return nil
}

func (p *osPlatform) OpenDefault(url string) error {
	root := os.Getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	c := exec.Command(winJoin(root, "System32", "rundll32.exe"), "url.dll,FileProtocolHandler", url)
	if err := c.Start(); err != nil {
		return err
	}
	go c.Wait()
	return nil
}

// AppPath reads HKCU then HKLM ...\App Paths\<exe> (default value).
func (p *osPlatform) AppPath(exe string) string {
	sub, _ := syscall.UTF16PtrFromString(`SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\` + exe)
	for _, root := range []syscall.Handle{syscall.HKEY_CURRENT_USER, syscall.HKEY_LOCAL_MACHINE} {
		var k syscall.Handle
		if syscall.RegOpenKeyEx(root, sub, 0, keyRead, &k) != nil {
			continue
		}
		buf := make([]uint16, 1024)
		n := uint32(len(buf) * 2)
		var typ uint32
		err := syscall.RegQueryValueEx(k, nil, nil, &typ, (*byte)(unsafe.Pointer(&buf[0])), &n)
		syscall.RegCloseKey(k)
		if err != nil || typ != syscall.REG_SZ {
			continue
		}
		v := strings.Trim(syscall.UTF16ToString(buf[:n/2]), `" `)
		if strings.HasSuffix(strings.ToLower(v), strings.ToLower(exe)) {
			return v
		}
	}
	return ""
}

// FirstInstance creates the named mutex and keeps its handle for the life of
// the process (Windows releases it on exit or crash). If the mutex already
// existed another launcher is running. If it cannot be created at all we
// act as the first instance: worst case is the old behaviour.
func (p *osPlatform) FirstInstance(name string) bool {
	n, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return true
	}
	h, _, callErr := procCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(n)))
	if h == 0 {
		return true
	}
	if errno, ok := callErr.(syscall.Errno); ok && errno == errorAlreadyExists {
		syscall.CloseHandle(syscall.Handle(h))
		return false
	}
	p.mutex = syscall.Handle(h)
	return true
}
