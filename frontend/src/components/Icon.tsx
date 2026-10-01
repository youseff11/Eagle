const warned = new Set<string>();

/**
 * An icon from the sprite the server page includes (`templates/partials/icons.html`).
 *
 * A name that is not in the sprite draws an empty box and says nothing - the
 * same trap as `{% icon %}` in the templates - so in development a missing name
 * is reported once. The sprite's names are the `i-…` ids in that file; there is
 * no `chat` (use `message`) and no `ic--xs` size.
 */
export function Icon({
  name,
  size,
  filled,
  className,
}: {
  name: string;
  size?: "sm" | "lg" | "xl";
  filled?: boolean;
  /** One more class of the design system (`ic--lead`: the icon inside a field). */
  className?: string;
}) {
  if (import.meta.env.DEV && typeof document !== "undefined") {
    const spriteIsPresent = document.getElementById("i-eagle") !== null;
    if (spriteIsPresent && !document.getElementById(`i-${name}`) && !warned.has(name)) {
      warned.add(name);
      console.warn(`Icon "${name}" is not in the sprite`);
    }
  }
  return (
    <svg
      className={`ic${size ? ` ic--${size}` : ""}${filled ? " ic--fill" : ""}${className ? ` ${className}` : ""}`}
      aria-hidden="true"
      focusable="false"
    >
      <use href={`#i-${name}`} />
    </svg>
  );
}
