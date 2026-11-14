// One color per unit. Used by the unit cards and by the Upcoming list
// (an assignment is drawn in the color of the unit it belongs to).
export const UNIT_COLORS: Record<string, string> = {
  "1": "#A63D40",
  "2": "#7A6F9B",
  "3": "#828C51",
  "4": "#7B506F",
  "5": "#758ECD",
  final: "#2E5EAA",
  other: "#2E5EAA",
};
// Used for Upcoming items that are not tied to a unit.
export const GOLD = "#8F713D";
export const unitColor = (key: string) => UNIT_COLORS[key] ?? "#2E5EAA";
