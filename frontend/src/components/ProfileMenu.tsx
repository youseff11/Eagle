import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { formErrors } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useChangePassword, useRemoveAvatar, useSetAvatar } from "../api/profileActions";
import type { MeResponse } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { NotAPicture, squareAvatar } from "../lib/avatarImage";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { useToasts } from "./Toasts";

/**
 * The person's own password, changed from their own menu: the one they have, and the new one twice. The password rides in the one
 * request that changes it and is not kept; every refusal is the server's (the current one wrong, too many tries, the project's
 * rules for a new one) and is said beside the boxes.
 */
function PasswordSection() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const change = useChangePassword();
  const [open, setOpen] = useState(false);
  const [boxes, setBoxes] = useState({ old_password: "", new_password1: "", new_password2: "" });
  const [problem, setProblem] = useState("");
  const ready = boxes.old_password !== "" && boxes.new_password1 !== "" && boxes.new_password2 !== "";

  const close = () => {
    setOpen(false);
    setProblem("");
    setBoxes({ old_password: "", new_password1: "", new_password2: "" });
    change.reset();
  };

  // What the server refused, in words: the current password, the lock, or the new password's own rules (its messages are Django's).
  const refused = (error: unknown) => {
    if (error instanceof ApiError && error.code === "wrong_password") return t("كلمة السر الحالية غلط.", "The current password is wrong.");
    if (error instanceof ApiError && error.code === "too_many_attempts") {
      return t("محاولات غلط كتير. جرّب بعد 15 دقيقة.", "Too many wrong tries. Try again in 15 minutes.");
    }
    const found = formErrors(error);
    const messages = found ? Object.values(found).flat() : [];
    return messages.length > 0 ? messages.join(" ") : t("كلمة السر ماتغيّرتش. جرّب تاني.", "The password was not changed. Try again.");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    change.mutate(boxes, {
      onSuccess: () => {
        close();
        push({ level: "success", title: t("كلمة السر اتغيّرت", "Password changed") });
      },
      onError: (error) => {
        // The boxes keep what was typed, but the request's copy of it does not stay in the mutation.
        change.reset();
        setProblem(refused(error));
      },
    });
  };

  const box = (name: keyof typeof boxes, label: string, autoComplete: string) => (
    <div className="profile__field">
      <label htmlFor={`profile-${name}`}>{label}</label>
      <input
        id={`profile-${name}`}
        className="input"
        type="password"
        dir="ltr"
        autoComplete={autoComplete}
        value={boxes[name]}
        onChange={(event) => setBoxes({ ...boxes, [name]: event.target.value })}
      />
    </div>
  );

  return (
    <div className="profile__section" data-section="password">
      <div className="profile__title">{t("كلمة السر", "Password")}</div>
      {!open ? (
        <button type="button" className="btn btn--block" onClick={() => setOpen(true)}>
          <Icon name="lock" size="sm" />
          {t("غيّر كلمة السر", "Change password")}
        </button>
      ) : (
        <form className="profile__form" onSubmit={submit}>
          {box("old_password", t("كلمة السر الحالية", "Current password"), "current-password")}
          {box("new_password1", t("كلمة السر الجديدة", "New password"), "new-password")}
          {box("new_password2", t("الجديدة تاني", "New password again"), "new-password")}
          {problem && (
            <div className="note note--high" role="alert">
              <Icon name="alert" />
              <div>{problem}</div>
            </div>
          )}
          <div className="profile__actions">
            <button type="submit" className="btn btn--primary btn--block" disabled={!ready || change.isPending}>
              <Icon name="check" size="sm" />
              {t("احفظ كلمة السر", "Save password")}
            </button>
            <button type="button" className="btn btn--ghost btn--block" onClick={close}>
              {t("إلغاء", "Cancel")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/**
 * The person's own chip in the top bar, and what opens from it: their picture, with the two things to do to it - put another
 * one there, or take it off - and their password (`PasswordSection`). The picture is cut to a square here before it is sent
 * (`squareAvatar`); what may be stored is the server's rule, which answers `bad_file` for anything else.
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
        <div className="profile__pop" id={panel} role="dialog" aria-label={t("البروفايل", "Profile")}>
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
          <PasswordSection />
        </div>
      )}
    </div>
  );
}
