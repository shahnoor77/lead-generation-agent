const colors: Record<string, string> = {
  DISCOVERED:        "bg-gray-100 text-gray-700",
  ENRICHED:          "bg-blue-100 text-blue-700",
  QUALIFIED:         "bg-green-100 text-green-700",
  OUTREACH_DRAFTED:  "bg-purple-100 text-purple-700",
  READY_FOR_REVIEW:  "bg-yellow-100 text-yellow-700",
  READY_TO_SEND:     "bg-orange-100 text-orange-700",
  CONTACTED:         "bg-cyan-100 text-cyan-700",
  REPLIED:           "bg-teal-100 text-teal-700",
  MEETING_SCHEDULED: "bg-indigo-100 text-indigo-700",
  WON:               "bg-emerald-100 text-emerald-700",
  LOST:              "bg-red-100 text-red-700",
  ARCHIVED:          "bg-gray-100 text-gray-400",
  QUALIFIED_ICP:     "bg-green-100 text-green-700",
  REJECTED:          "bg-red-100 text-red-600",
  PENDING_REVIEW:    "bg-yellow-100 text-yellow-700",
  APPROVED:          "bg-green-100 text-green-700",
};

export function Badge({ label }: { label: string }) {
  const cls = colors[label] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {label.replace(/_/g, " ")}
    </span>
  );
}
