import { useState, type ReactNode } from "react";
import { usePreferences } from "../i18n/Preferences";
import { Lightbox } from "./chat/Lightbox";

/**
 * A person's face: their own picture when they put one, their initials when not - and when the picture is not there any
 * more (taken off from another tab, a file that has gone), the initials too, never a broken image.
 *
 * `tone` is the colour the initials sit on (the top bar is the brand's, a colleague in the chats is the staff's, a list of
 * people in the panel has none); `className` adds the size (`avatar--xs`, `avatar--sm`, `avatar--lg`).
 *
 * `preview` is the person's name, for somebody else's face: when there is a picture it can be pressed, and it opens large with
 * the name under it. Where the face sits inside a link (a row of a list) leave it off: the press belongs to the link.
 */
export function Avatar({
  src,
  initials,
  tone = "brand",
  className = "",
  preview,
}: {
  src?: string | null;
  initials: string;
  tone?: "brand" | "staff" | "";
  className?: string;
  preview?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const shown = src && src !== failed ? src : null;
  const classes = ["avatar", tone && `avatar--${tone}`, className].filter(Boolean).join(" ");
  const face = (
    <span className={classes}>
      {shown ? <img className="avatar__img" src={shown} alt="" onError={() => setFailed(shown)} /> : initials}
    </span>
  );
  if (!shown || preview === undefined) return face;
  return (
    <Enlargeable url={shown} name={preview}>
      {face}
    </Enlargeable>
  );
}

/** The face as a button that opens the picture large. A separate part so that a plain face needs no preferences around it. */
function Enlargeable({ url, name, children }: { url: string; name: string; children: ReactNode }) {
  const { t } = usePreferences();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="avatar-btn"
        title={t("كبّر الصورة", "Enlarge the picture")}
        aria-label={`${t("كبّر صورة", "Enlarge the picture of")} ${name}`}
        onClick={() => setOpen(true)}
      >
        {children}
      </button>
      {open && <Lightbox images={[{ url, name }]} start={0} caption avatar onClose={() => setOpen(false)} />}
    </>
  );
}
