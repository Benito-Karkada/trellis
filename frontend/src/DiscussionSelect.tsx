import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import "./discussionSelect.css";

export type DiscussionOption = { value: string; label: string; group?: string };

export default function DiscussionSelect({ label, value, options, onChange, compact = false, disabled = false, className = "" }: {
  label: string;
  value: string;
  options: DiscussionOption[];
  onChange: (value: string) => void;
  compact?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState(0);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const choices = useRef<Array<HTMLButtonElement | null>>([]);
  const selected = options.findIndex(option => option.value === value);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  function openMenu() {
    if (disabled || options.length === 0) return;
    const next = Math.max(0, selected);
    setFocused(next);
    setOpen(true);
    requestAnimationFrame(() => choices.current[next]?.focus());
  }
  function choose(next: string) {
    onChange(next);
    setOpen(false);
    requestAnimationFrame(() => trigger.current?.focus());
  }
  function move(next: number) {
    const index = (next + options.length) % options.length;
    setFocused(index);
    choices.current[index]?.focus();
  }

  return <div className={`db-select ${compact ? "compact" : ""} ${className}`} ref={root}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false); }}>
    <button ref={trigger} type="button" className="db-select-trigger" aria-label={label} disabled={disabled}
      aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={() => open ? setOpen(false) : openMenu()}
      onKeyDown={event => {
        if (!open && ["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
          event.preventDefault(); openMenu();
        }
      }}>
      <span>{options[selected]?.label || "Choose an option"}</span><ChevronDown size={16} aria-hidden="true" />
    </button>
    {open && <div id={id} className="db-select-menu" role="listbox" aria-label={label}
      onKeyDown={event => {
        if (event.key === "ArrowDown") { event.preventDefault(); move(focused + 1); }
        else if (event.key === "ArrowUp") { event.preventDefault(); move(focused - 1); }
        else if (event.key === "Home") { event.preventDefault(); move(0); }
        else if (event.key === "End") { event.preventDefault(); move(options.length - 1); }
        else if (event.key === "Escape") { event.preventDefault(); setOpen(false); trigger.current?.focus(); }
      }}>
      {options.map((option, index) => <div key={option.value}>{option.group && (index === 0 || options[index - 1].group !== option.group) && <div className="db-select-group">{option.group}</div>}<button ref={element => { choices.current[index] = element; }}
        type="button" role="option" aria-selected={option.value === value} className={option.value === value ? "selected" : ""}
        onFocus={() => setFocused(index)} onClick={() => choose(option.value)}>
        <span>{option.label}</span>{option.value === value && <Check size={15} aria-hidden="true" />}
      </button></div>)}
    </div>}
  </div>;
}
