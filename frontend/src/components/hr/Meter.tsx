/** A score as a bar. No score draws an empty track: a missing indicator must look missing, not like zero. */
export function Meter({ score, band }: { score: number | null; band: string }) {
  if (score === null) {
    return (
      <div className="meter meter--empty" role="img" aria-label="not measured">
        <i style={{ width: 0 }} />
      </div>
    );
  }
  const width = Math.max(0, Math.min(100, Math.trunc(score)));
  return (
    <div className={`meter meter--${band}`} role="img" aria-label={`${width}%`}>
      <i style={{ width: `${width}%` }} />
    </div>
  );
}
