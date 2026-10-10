//go:build windows

package main

// The tray icon: one hidden top-level window (never shown) that owns a
// Shell_NotifyIcon entry, with its message loop on a locked OS thread.
// A hidden top-level window is used rather than a message-only window
// because only top-level windows get the "TaskbarCreated" broadcast (sent
// when Explorer restarts), which we need to put the icon back, and
// TrackPopupMenu needs a window that can be made foreground.

import (
	"errors"
	"runtime"
	"sync"
	"syscall"
	"unsafe"
)

const (
	wmNull          = 0x0000
	wmDestroy       = 0x0002
	wmClose         = 0x0010
	wmLButtonUp     = 0x0202
	wmLButtonDblClk = 0x0203
	wmRButtonUp     = 0x0205
	wmApp           = 0x8000
	wmTrayCallback  = wmApp + 1
	wmTrayNotice    = wmApp + 2 // posted by the Notices reader; the text waits in trayWin.pending

	nimAdd     = 0
	nimModify  = 1
	nimDelete  = 2
	nifMessage = 0x1
	nifIcon    = 0x2
	nifTip     = 0x4
	nifInfo    = 0x10

	niifInfo = 0x1 // balloon with the information icon

	// Sent in the low word of lParam of the tray callback (legacy behaviour:
	// no NOTIFYICON_VERSION_4). NIN_BALLOONUSERCLICK = WM_USER + 5.
	ninBalloonUserClick = 0x405

	mfString       = 0x0
	mfSeparator    = 0x800
	tpmRightButton = 0x0002
	tpmNoNotify    = 0x0080
	tpmReturnCmd   = 0x0100
	wsExToolWindow = 0x00000080
	wsPopup        = 0x80000000
	idiApplication = 32512

	errClassAlreadyExists = 1410

	cmdOpen      = 1
	cmdReconnect = 2
	cmdQuit      = 3
	cmdTerminal  = 4
)

var (
	shell32                    = syscall.NewLazyDLL("shell32.dll")
	procShellNotifyIconW       = shell32.NewProc("Shell_NotifyIconW")
	procGetModuleHandleW       = kernel32.NewProc("GetModuleHandleW")
	procRegisterClassExW       = user32.NewProc("RegisterClassExW")
	procCreateWindowExW        = user32.NewProc("CreateWindowExW")
	procDestroyWindow          = user32.NewProc("DestroyWindow")
	procDefWindowProcW         = user32.NewProc("DefWindowProcW")
	procGetMessageW            = user32.NewProc("GetMessageW")
	procTranslateMessage       = user32.NewProc("TranslateMessage")
	procDispatchMessageW       = user32.NewProc("DispatchMessageW")
	procPostMessageW           = user32.NewProc("PostMessageW")
	procPostQuitMessage        = user32.NewProc("PostQuitMessage")
	procRegisterWindowMessageW = user32.NewProc("RegisterWindowMessageW")
	procLoadIconW              = user32.NewProc("LoadIconW")
	procCreatePopupMenu        = user32.NewProc("CreatePopupMenu")
	procAppendMenuW            = user32.NewProc("AppendMenuW")
	procSetMenuDefaultItem     = user32.NewProc("SetMenuDefaultItem")
	procTrackPopupMenu         = user32.NewProc("TrackPopupMenu")
	procDestroyMenu            = user32.NewProc("DestroyMenu")
	procGetCursorPos           = user32.NewProc("GetCursorPos")
	procSetForegroundWindow    = user32.NewProc("SetForegroundWindow")
)

// notifyIconData mirrors NOTIFYICONDATAW (976 bytes on amd64).
type notifyIconData struct {
	CbSize           uint32
	HWnd             uintptr
	UID              uint32
	UFlags           uint32
	UCallbackMessage uint32
	HIcon            uintptr
	SzTip            [128]uint16
	DwState          uint32
	DwStateMask      uint32
	SzInfo           [256]uint16
	UVersion         uint32
	SzInfoTitle      [64]uint16
	DwInfoFlags      uint32
	GuidItem         [16]byte
	HBalloonIcon     uintptr
}

// wndClassEx mirrors WNDCLASSEXW (80 bytes on amd64).
type wndClassEx struct {
	CbSize        uint32
	Style         uint32
	LpfnWndProc   uintptr
	CbClsExtra    int32
	CbWndExtra    int32
	HInstance     uintptr
	HIcon         uintptr
	HCursor       uintptr
	HbrBackground uintptr
	LpszMenuName  *uint16
	LpszClassName *uint16
	HIconSm       uintptr
}

type winMsg struct {
	HWnd    uintptr
	Message uint32
	WParam  uintptr
	LParam  uintptr
	Time    uint32
	Pt      struct{ X, Y int32 }
	Private uint32
}

var (
	trayClassOnce sync.Once
	trayClassErr  error
	trayClassName = syscall.StringToUTF16Ptr("CommandCenterLauncherTray")
	trayInstance  uintptr

	// One tray at a time. The fields are touched only on the tray's own
	// thread, except alive/hwnd, which the stop goroutine reads under trayMu.
	trayMu     sync.Mutex
	trayCur    *trayWin
	trayBusy   bool
	taskbarMsg uint32
)

type trayWin struct {
	hwnd     uintptr
	menu     TrayMenu
	nid      notifyIconData
	alive    bool // false once WM_DESTROY ran: hwnd may not be posted to
	menuOpen bool
	pending  string // latest balloon text not yet shown; guarded by trayMu
}

// fillBalloon puts text into nid as an information balloon titled with the
// app name. Strings longer than the fixed buffers are cut (one slot is kept
// for the terminating zero).
func fillBalloon(nid *notifyIconData, text string) {
	nid.SzInfo = [256]uint16{}
	nid.SzInfoTitle = [64]uint16{}
	info, _ := syscall.UTF16FromString(text)
	copy(nid.SzInfo[:len(nid.SzInfo)-1], info)
	head, _ := syscall.UTF16FromString(title)
	copy(nid.SzInfoTitle[:len(nid.SzInfoTitle)-1], head)
	nid.DwInfoFlags = niifInfo
	nid.UFlags |= nifInfo
}

// showNotice raises the pending balloon on the tray's own thread. NIF_INFO is
// cleared again afterwards so that re-adding the icon (Explorer restart) does
// not pop the same balloon a second time.
func (w *trayWin) showNotice() {
	trayMu.Lock()
	text := w.pending
	w.pending = ""
	trayMu.Unlock()
	if text == "" {
		return
	}
	fillBalloon(&w.nid, text)
	procShellNotifyIconW.Call(nimModify, uintptr(unsafe.Pointer(&w.nid)))
	w.nid.UFlags &^= nifInfo
	w.nid.SzInfo = [256]uint16{}
	w.nid.SzInfoTitle = [64]uint16{}
	w.nid.DwInfoFlags = 0
}

// postNotice hands text to the tray thread. Like postClose, it holds trayMu
// so WM_DESTROY cannot have run when the handle is used.
func postNotice(w *trayWin, text string) {
	trayMu.Lock()
	defer trayMu.Unlock()
	if w.alive {
		w.pending = text
		procPostMessageW.Call(w.hwnd, wmTrayNotice, 0, 0)
	}
}

func registerTrayClass() error {
	trayClassOnce.Do(func() {
		trayInstance, _, _ = procGetModuleHandleW.Call(0)
		taskbarMsg = registerWindowMessage("TaskbarCreated")
		wc := wndClassEx{
			LpfnWndProc:   syscall.NewCallback(trayWndProc),
			HInstance:     trayInstance,
			LpszClassName: trayClassName,
		}
		wc.CbSize = uint32(unsafe.Sizeof(wc))
		r, _, err := procRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))
		if r == 0 {
			if errno, ok := err.(syscall.Errno); !ok || errno != errClassAlreadyExists {
				trayClassErr = err
			}
		}
	})
	return trayClassErr
}

func registerWindowMessage(name string) uint32 {
	r, _, _ := procRegisterWindowMessageW.Call(uintptr(unsafe.Pointer(syscall.StringToUTF16Ptr(name))))
	return uint32(r)
}

func (p *osPlatform) Tray(m TrayMenu, stop <-chan struct{}) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()

	trayMu.Lock()
	if trayBusy {
		trayMu.Unlock()
		return errors.New("a tray icon is already shown")
	}
	trayBusy = true
	trayMu.Unlock()
	defer func() {
		trayMu.Lock()
		trayBusy, trayCur = false, nil
		trayMu.Unlock()
	}()

	if err := registerTrayClass(); err != nil {
		return err
	}
	hwnd, _, err := procCreateWindowExW.Call(wsExToolWindow, uintptr(unsafe.Pointer(trayClassName)),
		uintptr(unsafe.Pointer(syscall.StringToUTF16Ptr(title))), wsPopup, 0, 0, 0, 0, 0, 0, trayInstance, 0)
	if hwnd == 0 {
		return err
	}
	w := &trayWin{hwnd: hwnd, menu: m, alive: true}
	w.nid.CbSize = uint32(unsafe.Sizeof(w.nid))
	w.nid.HWnd = hwnd
	w.nid.UID = 1
	w.nid.UFlags = nifMessage | nifIcon | nifTip
	w.nid.UCallbackMessage = wmTrayCallback
	w.nid.HIcon, _, _ = procLoadIconW.Call(0, idiApplication)
	tip, _ := syscall.UTF16FromString(m.Tip)
	copy(w.nid.SzTip[:len(w.nid.SzTip)-1], tip)

	trayMu.Lock()
	trayCur = w
	trayMu.Unlock()

	if r, _, err := procShellNotifyIconW.Call(nimAdd, uintptr(unsafe.Pointer(&w.nid))); r == 0 {
		w.nid.UFlags = 0 // nothing to delete
		procDestroyWindow.Call(hwnd)
		drainMessages()
		return errors.New("Shell_NotifyIcon failed: " + err.Error())
	}

	exited := make(chan struct{})
	defer close(exited)
	go func() {
		select {
		case <-stop:
			postClose(w)
		case <-exited:
		}
	}()
	if m.Notices != nil {
		go func() {
			for {
				select {
				case text := <-m.Notices:
					postNotice(w, text)
				case <-exited:
					return
				}
			}
		}()
	}

	var msg winMsg
	for {
		r, _, _ := procGetMessageW.Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0)
		if int32(r) <= 0 { // 0: WM_QUIT, -1: error
			break
		}
		procTranslateMessage.Call(uintptr(unsafe.Pointer(&msg)))
		procDispatchMessageW.Call(uintptr(unsafe.Pointer(&msg)))
	}
	return nil
}

// drainMessages runs the loop until WM_QUIT after a failed setup.
func drainMessages() {
	var msg winMsg
	for {
		r, _, _ := procGetMessageW.Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0)
		if int32(r) <= 0 {
			return
		}
		procDispatchMessageW.Call(uintptr(unsafe.Pointer(&msg)))
	}
}

// postClose asks the tray thread to close the window. Holding trayMu while
// posting means WM_DESTROY (which clears alive under trayMu) cannot have
// run, so the handle is still ours.
func postClose(w *trayWin) {
	trayMu.Lock()
	defer trayMu.Unlock()
	if w.alive {
		procPostMessageW.Call(w.hwnd, wmClose, 0, 0)
	}
}

func trayWndProc(hwnd, msg, wparam, lparam uintptr) uintptr {
	trayMu.Lock()
	w := trayCur
	trayMu.Unlock()
	if w == nil || w.hwnd != hwnd {
		if msg == wmDestroy {
			procPostQuitMessage.Call(0)
			return 0
		}
		r, _, _ := procDefWindowProcW.Call(hwnd, msg, wparam, lparam)
		return r
	}
	switch {
	case msg == wmTrayCallback:
		switch lparam & 0xffff {
		case wmLButtonDblClk, ninBalloonUserClick: // the balloon opens what Open opens
			go w.menu.Open()
		case wmLButtonUp, wmRButtonUp:
			w.showMenu()
		}
		return 0
	case msg == wmTrayNotice:
		w.showNotice()
		return 0
	case taskbarMsg != 0 && uint32(msg) == taskbarMsg: // Explorer restarted
		procShellNotifyIconW.Call(nimAdd, uintptr(unsafe.Pointer(&w.nid)))
		return 0
	case msg == wmClose:
		procDestroyWindow.Call(hwnd)
		return 0
	case msg == wmDestroy:
		if w.nid.UFlags != 0 {
			procShellNotifyIconW.Call(nimDelete, uintptr(unsafe.Pointer(&w.nid)))
		}
		trayMu.Lock()
		w.alive = false
		trayMu.Unlock()
		procPostQuitMessage.Call(0)
		return 0
	}
	r, _, _ := procDefWindowProcW.Call(hwnd, msg, wparam, lparam)
	return r
}

func (w *trayWin) showMenu() {
	if w.menuOpen {
		return
	}
	w.menuOpen = true
	defer func() { w.menuOpen = false }()
	menu, _, _ := procCreatePopupMenu.Call()
	if menu == 0 {
		return
	}
	defer procDestroyMenu.Call(menu)
	add := func(id uintptr, text string) {
		procAppendMenuW.Call(menu, mfString, id, uintptr(unsafe.Pointer(syscall.StringToUTF16Ptr(text))))
	}
	add(cmdOpen, "Open Command Center")
	add(cmdReconnect, "Reconnect")
	if w.menu.Terminal != nil {
		add(cmdTerminal, "Open server terminal")
	}
	procAppendMenuW.Call(menu, mfSeparator, 0, 0)
	add(cmdQuit, "Quit (stop the tunnel)")
	procSetMenuDefaultItem.Call(menu, cmdOpen, 0)

	var pt struct{ X, Y int32 }
	procGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))
	// Foreground + WM_NULL afterwards: without them the menu does not close
	// when the user clicks elsewhere (documented Shell_NotifyIcon quirk).
	procSetForegroundWindow.Call(w.hwnd)
	cmd, _, _ := procTrackPopupMenu.Call(menu, tpmRightButton|tpmNoNotify|tpmReturnCmd,
		uintptr(pt.X), uintptr(pt.Y), 0, w.hwnd, 0)
	procPostMessageW.Call(w.hwnd, wmNull, 0, 0)

	switch cmd {
	case cmdOpen:
		go w.menu.Open()
	case cmdReconnect:
		go w.menu.Reconnect()
	case cmdTerminal:
		if w.menu.Terminal != nil {
			go w.menu.Terminal()
		}
	case cmdQuit:
		procPostMessageW.Call(w.hwnd, wmClose, 0, 0)
	}
}
