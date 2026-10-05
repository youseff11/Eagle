import { useState } from "react";

/**
 * A person's face: their own picture when they put one, their initials when not - and when the picture is not there any
 * more (taken off from another tab, a file that has gone), the initials too, never a broken image.
 *
 * `tone` is the colour the initials sit on (the top bar is the brand's, a colleague in the chats is the staff's, a list of
 * people in the panel has none); `className` adds the size (`avatar--xs`, `avatar--sm`, `avatar--lg`).
 */
export function Avatar({
  src,
  initials,
  tone = "brand",
  className = "",
}: {
  src?: string | null;
  initials: string;
  tone?: "brand" | "staff" | "";
  className?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const shown = src && src !== failed ? src : null;
  const classes = ["avatar", tone && `avatar--${tone}`, className].filter(Boolean).join(" ");
  return (
    <span className={classes}>
      {shown ? <img className="avatar__img" src={shown} alt="" onError={() => setFailed(shown)} /> : initials}
    </span>
  );
}
