export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white border border-gray-200 rounded-lg p-4 ${className}`}>
      {children}
    </div>
  );
}

export function MetricCard({ label, value, color = "text-gray-900" }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 text-center">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  );
}
