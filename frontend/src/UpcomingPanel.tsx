import { unitColor, GOLD } from "./unitColors";

export type UpcomingItem = {
  id: string | number;
  title: string;
  /** Already formatted, e.g. "Nov 13 at 11:59pm". Rendered as "Due …". */
  due: string;
  /** Already formatted, e.g. "-/31 pts" or "31/31 pts". */
  points: string;
  /** "1"–"5", "final" or "other". Colors the title like that unit. Omit for gold. */
  unitKey?: string;
  done?: boolean;
};

/**
 * The Upcoming to-do list. It is intentionally empty until someone passes `items`;
 * all of the formatting (checkbox, colored title, points on the right, due date
 * underneath) is already in place.
 *
 * Pass `onToggle` to control the checkboxes. Without it the boxes still tick
 * and strike through locally.
 */
export default function UpcomingPanel({
  items = [],
  onToggle,
}: {
  items?: UpcomingItem[];
  onToggle?: (id: UpcomingItem["id"], done: boolean) => void;
}) {
  return (
    <div className="ch-upcoming">
      <h3 className="ch-upcoming-title">Upcoming</h3>
      {items.length > 0 && (
        <ul className="ch-upcoming-list">
          {items.map((item) => {
            const color = item.unitKey ? unitColor(item.unitKey) : GOLD;
            const checkProps = onToggle
              ? { checked: !!item.done, onChange: (e: React.ChangeEvent<HTMLInputElement>) => onToggle(item.id, e.target.checked) }
              : { defaultChecked: !!item.done };
            return (
              <li key={item.id} className="ch-upcoming-item">
                <input
                  type="checkbox"
                  className="ch-upcoming-check"
                  aria-label={`Mark ${item.title} complete`}
                  style={{ accentColor: color }}
                  {...checkProps}
                />
                <div className="ch-upcoming-body">
                  <div className="ch-upcoming-row">
                    <span className="ch-upcoming-name" style={{ color }}>{item.title}</span>
                    <span className="ch-upcoming-points">{item.points}</span>
                  </div>
                  <div className="ch-upcoming-due">Due {item.due}</div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
