import { useState } from "react";
import { usePreferences } from "../../i18n/Preferences";
import { localSrc } from "../../lib/localPhotos";
import { Lightbox, type LightboxImage } from "./Lightbox";

/** How many photos the grid draws; the rest are the number on the last one. */
export const GRID_TILES = 4;

/**
 * Photos sent together, drawn as WhatsApp draws them: one block of up to four tiles (the fourth says «+N» when there are
 * more), and a press on any opens them one by one, in order, starting from that one. `images` holds only addresses the page
 * already checked are paths on this site.
 */
export function ImageGrid({ images }: { images: LightboxImage[] }) {
  const { t } = usePreferences();
  const [open, setOpen] = useState<number | null>(null);
  const shown = images.slice(0, GRID_TILES);
  const more = images.length - shown.length;
  return (
    <>
      <div className={`imggrid imggrid--${shown.length}`} data-images={images.length}>
        {shown.map((image, index) => (
          <button
            key={`${image.url}-${index}`}
            type="button"
            className="imggrid__tile"
            title={image.name}
            aria-label={`${t("افتح الصورة", "Open the photo")} ${index + 1}: ${image.name}`}
            onClick={() => setOpen(index)}
          >
            <img src={localSrc(image.url)} alt={image.name} loading="lazy" />
            {more > 0 && index === shown.length - 1 && <span className="imggrid__more">+{more}</span>}
          </button>
        ))}
      </div>
      {open !== null && <Lightbox images={images} start={open} onClose={() => setOpen(null)} />}
    </>
  );
}
