// useResizableTable
// Lightweight, dependency-free column-width + row-height resizing for tables.
// Column widths live in React state and are applied via a <colgroup>; row
// heights live in a keyed map and are applied via per-row style.
//
// Drag correctness (July-2026 fix for "messy" grips):
//   * The table must set an explicit width equal to the SUM of the column
//     widths (use the returned `total`). With `width:100%` the browser
//     re-distributes the container width across ALL columns, so dragging one
//     grip visibly moved every column and the grip escaped the pointer.
//   * Pointer capture pins the drag to the grip element — releasing outside
//     the window can no longer leave a "stuck" drag following the cursor.
//   * Widths/heights are clamped to sane min/max so a wild drag cannot blow
//     a column across the viewport.
//   * The body cursor + text selection are suppressed for the duration of
//     the drag (same treatment as the panel splitter).
//
// Usage in a component:
//   const rt = useResizableTable([64, 112, 56]);
//   <div className="overflow-x-auto">
//     <table className="fp-rt" style={{ width: rt.total }}>
//       <colgroup>{rt.cols.map((w,i)=><col key={i} style={{width:w}}/>)}</colgroup>
//       <thead><tr>
//         <th className="relative">Layer
//           <span className="fp-col-grip" onPointerDown={e=>rt.startColResize(0,e)}
//                 onDoubleClick={()=>rt.resetCol(0)} />
//         </th> ...
//       </tr></thead>
//       ...
//     </table>
//   </div>

import { useState, useCallback, useRef } from "react";

export function useResizableTable(initialColWidths, opts = {}) {
  const minCol = opts.minCol ?? 40;
  const maxCol = opts.maxCol ?? 480;
  const minRow = opts.minRow ?? 24;
  const maxRow = opts.maxRow ?? 160;
  const initialRef = useRef([...initialColWidths]);
  const [cols, setCols] = useState(initialColWidths);
  const [rowH, setRowH] = useState({}); // rowKey -> px height

  const total = cols.reduce((s, w) => s + w, 0);

  // Double-click a grip to restore that column's seed width.
  const resetCol = useCallback((i) => {
    setCols((prev) => {
      const n = [...prev];
      if (initialRef.current[i] != null) n[i] = initialRef.current[i];
      return n;
    });
  }, []);

  const startColResize = useCallback((i, ev) => {
    if (ev.pointerType === "mouse" && ev.button !== 0) return;
    ev.preventDefault();
    ev.stopPropagation();
    const grip = ev.currentTarget;
    const th = grip.parentElement;
    const startW = th ? th.getBoundingClientRect().width : 80;
    const startX = ev.clientX;
    grip.classList.add("fp-active");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    // Pin the drag to the grip: with capture, move/up fire on the grip even
    // when the pointer leaves it (or the window). No orphaned window
    // listeners, no stuck drags.
    try { grip.setPointerCapture(ev.pointerId); } catch { /* fall back to window events */ }

    const onMove = (e) => {
      const w = Math.min(maxCol, Math.max(minCol, startW + (e.clientX - startX)));
      setCols((prev) => {
        if (prev[i] === w) return prev;
        const n = [...prev]; n[i] = w; return n;
      });
    };
    const end = () => {
      grip.classList.remove("fp-active");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", end);
      grip.removeEventListener("pointercancel", end);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
    // Grip listeners cover the captured path; window listeners are the
    // fallback when setPointerCapture is unavailable.
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", end);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  }, [minCol, maxCol]);

  const startRowResize = useCallback((rowKey, ev) => {
    if (ev.pointerType === "mouse" && ev.button !== 0) return;
    ev.preventDefault();
    ev.stopPropagation();
    const grip = ev.currentTarget;
    const tr = grip.closest("tr");
    const startH = tr ? tr.getBoundingClientRect().height : minRow;
    const startY = ev.clientY;
    grip.classList.add("fp-active");
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
    try { grip.setPointerCapture(ev.pointerId); } catch { /* fall back to window events */ }

    const onMove = (e) => {
      const h = Math.min(maxRow, Math.max(minRow, startH + (e.clientY - startY)));
      setRowH((prev) => (prev[rowKey] === h ? prev : { ...prev, [rowKey]: h }));
    };
    const end = () => {
      grip.classList.remove("fp-active");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", end);
      grip.removeEventListener("pointercancel", end);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", end);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  }, [minRow, maxRow]);

  return { cols, setCols, total, rowH, startColResize, startRowResize, resetCol };
}
