/** Fixed page decoration: faint gold/cyan radial glows and a very subtle hex grid. */
export function Background() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-bg">
      <div className="absolute -top-[20%] -left-[15%] h-[70vh] w-[70vw] rounded-full bg-[radial-gradient(closest-side,rgba(200,170,110,0.06),transparent)]" />
      <div className="absolute -right-[15%] -bottom-[25%] h-[75vh] w-[70vw] rounded-full bg-[radial-gradient(closest-side,rgba(10,200,185,0.05),transparent)]" />
      <svg className="absolute inset-0 h-full w-full opacity-[0.035] [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]">
        <defs>
          <pattern id="hextrack-hexgrid" width="28" height="48.5" patternUnits="userSpaceOnUse" patternTransform="scale(1.1)">
            <path
              d="M14 0 L28 8.08 L28 24.25 L14 32.33 L0 24.25 L0 8.08 Z M14 32.33 L14 48.5"
              fill="none"
              stroke="#ffffff"
              strokeWidth="1"
            />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#hextrack-hexgrid)" />
      </svg>
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-gold/30 to-transparent" />
    </div>
  );
}
