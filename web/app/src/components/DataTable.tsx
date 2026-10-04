// A real <table> with keyboard navigation (j/k or arrows, Enter to open,
// Esc to collapse), roving focus, optional sort and an inline expansion row.
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export interface Column<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  className?: string;
  sort?: (a: T, b: T) => number;
  width?: number | string;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  label: string;
  selected?: string | null;
  onSelect?: (key: string, row: T) => void;
  onActivate?: (key: string, row: T) => void;
  expanded?: string | null;
  renderExpansion?: (row: T) => ReactNode;
  rowClass?: (row: T) => string;
  empty?: ReactNode;
  initialSort?: { id: string; dir: 1 | -1 };
  onKeyExtra?: (e: KeyboardEvent, row: T) => boolean;
}

export function DataTable<T>({ rows, columns, rowKey, label, selected, onSelect, onActivate, expanded, renderExpansion,
  rowClass, empty, initialSort, onKeyExtra }: Props<T>) {
  const [sort, setSort] = useState(initialSort ?? null);
  const body = useRef<HTMLTableSectionElement>(null);
  const sorted = useMemo(() => {
    const col = sort && columns.find((c) => c.id === sort.id);
    if (!col?.sort) return rows;
    return [...rows].sort((a, b) => col.sort!(a, b) * sort!.dir);
  }, [rows, columns, sort]);
  const keys = useMemo(() => sorted.map(rowKey), [sorted, rowKey]);
  const current = selected && keys.includes(selected) ? selected : keys[0] ?? null;

  const focusRow = (k: string) => {
    const el = body.current?.querySelector<HTMLTableRowElement>(`tr[data-key="${CSS.escape(k)}"]`);
    el?.focus();
    el?.scrollIntoView({ block: "nearest" });
  };

  // Keep focus on the selected row when it moves under the keyboard.
  const lastSel = useRef(selected);
  useEffect(() => {
    if (selected && selected !== lastSel.current && body.current?.contains(document.activeElement)) focusRow(selected);
    lastSel.current = selected;
  }, [selected]);

  const onKey = (e: KeyboardEvent<HTMLTableRowElement>, row: T, k: string) => {
    if (onKeyExtra?.(e, row)) return;
    // Only plain keys on the row itself: Ctrl+K is the palette, Enter on a link is the link's.
    if (e.ctrlKey || e.metaKey || e.altKey || e.target !== e.currentTarget) return;
    const i = keys.indexOf(k);
    const move = (j: number) => {
      const nk = keys[Math.max(0, Math.min(keys.length - 1, j))];
      if (!nk) return;
      onSelect?.(nk, sorted[keys.indexOf(nk)]);
      focusRow(nk);
    };
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); move(i + 1); }
    else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); move(i - 1); }
    else if (e.key === "Home") { e.preventDefault(); move(0); }
    else if (e.key === "End") { e.preventDefault(); move(keys.length - 1); }
    else if (e.key === "Enter") { e.preventDefault(); onActivate?.(k, row); }
  };

  if (!rows.length && empty) return <>{empty}</>;
  return <table className="tbl" aria-label={label}>
    <thead><tr>{columns.map((c) => {
      const active = sort?.id === c.id;
      return <th key={c.id} scope="col" className={c.className} style={c.width ? { width: c.width } : undefined}
        aria-sort={active ? (sort!.dir === 1 ? "ascending" : "descending") : undefined}>
        {c.sort ? <button type="button" onClick={() => setSort(active ? { id: c.id, dir: (sort!.dir * -1) as 1 | -1 }
          : { id: c.id, dir: 1 })}>{c.header}{active ? (sort!.dir === 1 ? " ↑" : " ↓") : ""}</button> : c.header}
      </th>;
    })}</tr></thead>
    <tbody ref={body}>{sorted.map((row) => {
      const k = rowKey(row);
      const isSel = k === current && selected != null;
      return <Fragment key={k}>
        <tr data-key={k} tabIndex={k === current ? 0 : -1} aria-selected={isSel}
          aria-expanded={renderExpansion ? expanded === k : undefined}
          className={`${onActivate || onSelect ? "is-click " : ""}${rowClass?.(row) ?? ""}`}
          onClick={() => { onSelect?.(k, row); onActivate?.(k, row); }}
          onKeyDown={(e) => onKey(e, row, k)}>
          {columns.map((c) => <td key={c.id} className={c.className}>{c.cell(row)}</td>)}
        </tr>
        {renderExpansion && expanded === k && <tr className="expand"><td colSpan={columns.length}>{renderExpansion(row)}</td></tr>}
      </Fragment>;
    })}</tbody>
  </table>;
}
