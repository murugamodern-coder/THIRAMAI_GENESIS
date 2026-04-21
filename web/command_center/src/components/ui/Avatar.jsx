export default function Avatar({ src, name = "", size = "md", status = null }) {
  const initials = String(name || "?")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
  return (
    <span className={`ui-avatar ui-avatar--${size}`}>
      {src ? <img src={src} alt={name || "Avatar"} loading="lazy" /> : <span>{initials || "?"}</span>}
      {status ? <span className={`ui-avatar__status ui-avatar__status--${status}`} aria-hidden="true" /> : null}
    </span>
  );
}
