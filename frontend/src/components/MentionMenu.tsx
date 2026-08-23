import clsx from "clsx";
import { Wrench, Cpu } from "lucide-react";
import type { Mention } from "../types";

/** Menu de autocompletado para "@" en el chat. Se ancla al contenedor del
 * input, no al pixel exacto del cursor -evita medir la posicion del caret
 * en un textarea plano. */
export function MentionMenu({
  items,
  activeIndex,
  onSelect,
}: {
  items: Mention[];
  activeIndex: number;
  onSelect: (item: Mention) => void;
}) {
  if (items.length === 0) return null;

  return (
    <div className="card absolute bottom-full left-0 mb-2 w-64 overflow-hidden p-1 shadow-lg">
      {items.map((item, index) => (
        <button
          key={item.id}
          type="button"
          onMouseDown={(event) => {
            event.preventDefault(); // no perder el foco del textarea
            onSelect(item);
          }}
          className={clsx(
            "flex w-full items-start gap-2 rounded-[8px] px-2.5 py-1.5 text-left text-[13px]",
            index === activeIndex ? "bg-accent-50 dark:bg-accent-700/15" : "hover:bg-[var(--surface-soft)]",
          )}
        >
          {item.kind === "tool" ? (
            <Wrench className="mt-0.5 size-3.5 shrink-0 text-accent-500" />
          ) : (
            <Cpu className="mt-0.5 size-3.5 shrink-0 text-accent-500" />
          )}
          <span className="min-w-0">
            <span className="block font-medium">@{item.label}</span>
            <span className="block truncate text-[11.5px] muted">{item.description}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
