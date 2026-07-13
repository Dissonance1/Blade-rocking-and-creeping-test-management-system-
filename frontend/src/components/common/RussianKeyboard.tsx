/**
 * RussianKeyboard — on-screen ЙЦУКЕН virtual keyboard for fields that need
 * Cyrillic input (e.g. Melt Number) on touch/kiosk stations without a
 * physical Russian keyboard layout attached.
 *
 * The preview is a real <input> so the cursor/selection can be moved (click,
 * drag-select, or the ←/→ keys below) and keypresses insert/replace at that
 * position instead of always appending to the end.
 */

import { useRef, useState } from "react";
import { Delete, Space, CornerDownLeft, ArrowUp, ArrowLeft, ArrowRight, X, Keyboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";

const DIGIT_ROW = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];
const LETTER_ROWS = [
  ["й", "ц", "у", "к", "е", "н", "г", "ш", "щ", "з", "х", "ъ"],
  ["ф", "ы", "в", "а", "п", "р", "о", "л", "д", "ж", "э"],
  ["я", "ч", "с", "м", "и", "т", "ь", "б", "ю", "."],
];

interface RussianKeyboardProps {
  initialValue: string;
  onConfirm: (value: string) => void;
  onClose: () => void;
}

export default function RussianKeyboard({ initialValue, onConfirm, onClose }: RussianKeyboardProps) {
  const [value, setValue] = useState(initialValue);
  const [shift, setShift] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const selection = () => {
    const el = inputRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    return { start, end };
  };

  const placeCursor = (pos: number) => {
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(pos, pos);
    });
  };

  const insert = (text: string) => {
    const { start, end } = selection();
    setValue((v) => v.slice(0, start) + text + v.slice(end));
    placeCursor(start + text.length);
  };

  const press = (char: string) => insert(shift ? char.toUpperCase() : char);
  const space = () => insert(" ");

  const backspace = () => {
    const { start, end } = selection();
    if (start === end) {
      if (start === 0) return;
      setValue((v) => v.slice(0, start - 1) + v.slice(end));
      placeCursor(start - 1);
    } else {
      setValue((v) => v.slice(0, start) + v.slice(end));
      placeCursor(start);
    }
  };

  const moveCursor = (delta: number) => {
    const { start, end } = selection();
    const pos = Math.max(0, Math.min(value.length, (start === end ? start : delta < 0 ? start : end) + delta));
    placeCursor(pos);
  };

  const clear = () => {
    setValue("");
    placeCursor(0);
  };

  const confirm = () => {
    onConfirm(value);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="relative w-full max-w-xl mx-0 sm:mx-4 bg-slate-900 rounded-t-2xl sm:rounded-2xl shadow-2xl overflow-hidden border border-slate-700">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-slate-800/80 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <Keyboard className="w-4 h-4 text-orange-400" />
            <span className="text-sm font-semibold text-white">Russian Keyboard</span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close keyboard"
            className="p-3 -m-3 rounded-full text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Preview input — click/drag inside it to move the cursor or select a range */}
        <div className="px-4 pt-3">
          <div className="flex items-center justify-between gap-2 rounded-xl border border-slate-600 bg-slate-800 px-3 py-2.5">
            <input
              ref={inputRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Melt number…"
              className="flex-1 min-w-0 bg-transparent font-mono text-base text-white placeholder:text-slate-500 focus:outline-none"
            />
            <button
              onClick={clear}
              className="shrink-0 text-xs text-slate-400 hover:text-slate-200"
            >
              Clear
            </button>
          </div>
        </div>

        {/* Keys */}
        <div className="px-4 py-3 space-y-1.5">
          <div className="flex gap-1.5 justify-center">
            {DIGIT_ROW.map((d) => (
              <Key key={d} onClick={() => press(d)}>{d}</Key>
            ))}
          </div>

          {LETTER_ROWS.map((row, i) => (
            <div key={i} className="flex gap-1.5 justify-center">
              {i === 2 && (
                <Key onClick={() => setShift((s) => !s)} active={shift} wide>
                  <ArrowUp className="w-4 h-4" />
                </Key>
              )}
              {row.map((ch) => (
                <Key key={ch} onClick={() => press(ch)}>{shift ? ch.toUpperCase() : ch}</Key>
              ))}
              {i === 2 && (
                <Key onClick={backspace} wide>
                  <Delete className="w-4 h-4" />
                </Key>
              )}
            </div>
          ))}

          <div className="flex gap-1.5 justify-center pt-1">
            <Key onClick={() => moveCursor(-1)} wide title="Move cursor left">
              <ArrowLeft className="w-4 h-4" />
            </Key>
            <Key onClick={space} wide2>
              <Space className="w-4 h-4" />
            </Key>
            <Key onClick={() => moveCursor(1)} wide title="Move cursor right">
              <ArrowRight className="w-4 h-4" />
            </Key>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2 px-4 pb-4 pt-2">
          <Button
            type="button"
            variant="outline"
            className="flex-1 border-slate-600 text-slate-300 hover:bg-slate-700"
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            type="button"
            className="flex-1 bg-orange-500 hover:bg-orange-400 text-white"
            onClick={confirm}
          >
            <CornerDownLeft className="w-4 h-4 mr-1" />
            Use This Value
          </Button>
        </div>
      </div>
    </div>
  );
}

function Key({
  children,
  onClick,
  active,
  wide,
  wide2,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  wide?: boolean;
  wide2?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className={cn(
        "h-10 rounded-lg text-sm font-medium flex items-center justify-center transition-colors shrink-0",
        wide2 ? "w-40" : wide ? "w-14" : "w-9",
        active
          ? "bg-orange-500 text-white"
          : "bg-slate-700 text-slate-100 hover:bg-slate-600"
      )}
    >
      {children}
    </button>
  );
}
