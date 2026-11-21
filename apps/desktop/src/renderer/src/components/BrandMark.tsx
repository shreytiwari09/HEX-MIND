import { useId } from 'react'

/** The H.E.X Mind mark: a hexagon (the hive of specialist agents) holding an H whose crossbar
 * is a small hexagon (the shared mind). Source: design/logo/mark.svg. */
export function BrandMark({ size = 22 }: { size?: number }): React.JSX.Element {
  const id = useId()
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 100 100"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8b8ff7" />
          <stop offset="1" stopColor="#4f46e5" />
        </linearGradient>
      </defs>
      <path
        d="M42.21,7.5 Q50,3 57.79,7.5 L82.91,22 Q90.7,26.5 90.7,35.5 L90.7,64.5 Q90.7,73.5 82.91,78 L57.79,92.5 Q50,97 42.21,92.5 L17.09,78 Q9.3,73.5 9.3,64.5 L9.3,35.5 Q9.3,26.5 17.09,22 Z"
        fill={`url(#${id})`}
      />
      <rect x="27" y="27" width="11" height="46" rx="3" fill="#fff" />
      <rect x="62" y="27" width="11" height="46" rx="3" fill="#fff" />
      <rect x="36" y="46.5" width="28" height="7" fill="#fff" />
      <polygon points="50,41 57.79,45.5 57.79,54.5 50,59 42.21,54.5 42.21,45.5" fill="#fff" />
    </svg>
  )
}
