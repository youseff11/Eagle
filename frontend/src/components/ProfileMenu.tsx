import { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { useRemoveAvatar, useSetAvatar } from "../api/profileActions";
import type { MeResponse } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { NotAPicture, squareAvatar } from "../lib/avatarImage";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { useToasts } from "./Toasts";

/**
 * The person's own chip in the top bar, and what opens from it: their picture, with the two things to do to it - put another
 * one there, or take it off. The picture is cut to a square here before it is sent (`squareAvatar`); what may be stored is the
 * server's rule, which answers `bad_file` for anything else.
 */
export function ProfileMenu({ user, roleLabel }: { user: MeResponse["user"]; roleLabel: string }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const panel = useId();
  const set = useSetAvatar();
  const remove = useRemoveAvatar();
  const busy = set.isPending || remove.isPending;

  // Out with a press anywhere else or Escape (which gives the focus back to the chip).
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const toggle = () => {
    setProblem("");
    setOpen((now) => !now);
  };

  const failed = (error: unknown, fallback: string) =>
    setProblem(
      error instanceof NotAPicture || (error instanceof ApiError && error.code === "bad_file")
        ? t("الملف ده مش صورة أقدر أحفظها. جرّب صورة JPG أو PNG.", "That file is not a picture I can keep. Try a JPG or PNG.")
        : fallback,
    );

  const choose = async (file: File | undefined) => {
    if (picker.current) picker.current.value = "";
    if (!file) return;
    setProblem("");
    try {
      const square = await squareAvatar(file);
      set.mutate(square, {
        onSuccess: () => push({ level: "success", title: t("صورة البروفايل اتحدّثت", "Profile picture updated") }),
        onError: (error) => failed(error, t("الصورة ماتحفظتش. جرّب تاني.", "The picture was not saved. Try again.")),
      });
    } catch (error) {
      failed(error, t("مقدرتش أقرا الصورة.", "Could not read the picture."));
    }
  };

  const take = () => {
    setProblem("");
    remove.mutate(undefined, {
      onSuccess: () => push({ level: "success", title: t("صورة البروفايل اتحذفت", "Profile picture removed") }),
      onError: (error) => failed(error, t("الصورة ماتحذفتش. جرّب تاني.", "The picture was not removed. Try again.")),
    });
  };

  return (
    <div className="profile" ref={root}>
      <button
        type="button"
        ref={trigger}
        className="topbar__user profile__btn"
        title={user.short_name}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panel : undefined}
        onClick={toggle}
      >
        <Avatar src={user.avatar} initials={user.initials} className="topbar__face" />
        <span className="topbar__who">
          <span className="topbar__who-name">{user.short_name}</span>
          <span className="chip">{roleLabel}</span>
        </span>
      </button>

      {open && (
        <div className="profile__pop" id={panel} role="dialog" aria-label={t("صورة البروفايل", "Profile picture")}>
          <div className="profile__head">
            <Avatar src={user.avatar} initials={user.initials} className="profile__face" />
            <div className="profile__who">
              <div className="profile__name">{user.name}</div>
              <span className="chip">{roleLabel}</span>
            </div>
          </div>
          <div className="profile__title">{t("صورة البروفايل", "Profile picture")}</div>
          <input
            ref={picker}
            type="file"
            accept="image/*"
            hidden
            data-testid="avatar-file"
            onChange={(event) => void choose(event.target.files?.[0])}
          />
          <div className="profile__actions">
            <button type="button" className="btn btn--primary btn--block" disabled={busy} onClick={() => picker.current?.click()}>
              <Icon name="upload" size="sm" />
              {user.avatar ? t("غيّر الصورة", "Change picture") : t("ارفع صورة", "Upload a picture")}
            </button>
            {user.avatar && (
              <button type="button" className="btn btn--danger btn--block" disabled={busy} onClick={take}>
                <Icon name="trash" size="sm" />
                {t("احذف الصورة", "Remove picture")}
              </button>
            )}
          </div>
          <div className="profile__hint">
            {t("بتتقص مربعة تلقائيًا. JPG أو PNG أو WebP.", "Cropped to a square automatically. JPG, PNG or WebP.")}
          </div>
          {problem && (
            <div className="note note--high mt" role="alert">
              <Icon name="alert" />
              <div>{problem}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
