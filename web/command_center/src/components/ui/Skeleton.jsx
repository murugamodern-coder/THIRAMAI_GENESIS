export default function Skeleton({ variant = "text", className = "" }) {
  if (variant === "card") return <div className={`ui-skeleton ${className}`} style={{ height: 140 }} aria-hidden="true" />;
  if (variant === "avatar") return <div className={`ui-skeleton ${className}`} style={{ width: 40, height: 40, borderRadius: "9999px" }} aria-hidden="true" />;
  if (variant === "chart") return <div className={`ui-skeleton ${className}`} style={{ height: 220 }} aria-hidden="true" />;
  if (variant === "table") return <div className={`ui-skeleton ${className}`} style={{ height: 180 }} aria-hidden="true" />;
  return <div className={`ui-skeleton ${className}`} style={{ height: 12 }} aria-hidden="true" />;
}
