import { useState } from "react";
import { useLinkWaNumber, useRefreshWaNumbers, useSendWaCode, waFailure } from "../../api/adminActions";
import type { WaNumber } from "../../api/types";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";
import { usePreferences } from "../../i18n/Preferences";

/** What a number is used for, in words. */
function Use({ row }: { row: WaNumber }) {
  const { t } = usePreferences();
  const use = row.use;
  if (use.kind === "company") return <span className="chip">{t("رقم الشركة", "Company number")}</span>;
  if (use.kind === "recruit") return <span className="chip">{t("خط التوظيف", "Hiring line")}</span>;
  if (use.kind === "person") return <span className="chip">{`${t("مع", "With")} ${use.name}`}</span>;
  return <span className="muted">{t("مش متحدد لحد", "Nobody's yet")}</span>;
}

/**
 * One number that is not on the Cloud API yet: ask for the code, type it, and the number is verified and registered at once
 * (`walines.link`). The six digits are enough - the link starts by itself as the last one is typed.
 */
function LinkNumber({ row, onDone }: { row: WaNumber; onDone: () => void }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const send = useSendWaCode();
  const link = useLinkWaNumber();
  const [code, setCode] = useState("");
  const [pin, setPin] = useState("");
  const [sent, setSent] = useState(false);
  const [problem, setProblem] = useState("");

  const words = (error: unknown, fallback: [string, string]) => {
    const failure = waFailure(error);
    if (failure) return lang === "ar" ? failure.error_ar || failure.error_en : failure.error_en || failure.error_ar;
    return t(...fallback);
  };
  const ask = (method: "SMS" | "VOICE") => {
    setProblem("");
    send.mutate(
      { id: row.id, method },
      {
        onSuccess: () => {
          setSent(true);
          push({ level: "success", title: t("الكود اتبعت", "The code was sent") });
        },
        onError: (error) => setProblem(words(error, ["مقدرتش أبعت الكود.", "Could not send the code."])),
      },
    );
  };
  const run = (typed: string) => {
    if (link.isPending) return;
    setProblem("");
    link.mutate(
      { id: row.id, code: typed, pin: pin.trim() },
      {
        onSuccess: (answer) => {
          setCode("");
          setPin("");
          // What a send-out carried is not kept in the request's own state once it is done (the PIN among it).
          link.reset();
          push({ level: "success", title: `${t("الرقم اتربط", "The number is linked")} ${answer.number.number}` });
          onDone();
        },
        onError: (error) => setProblem(words(error, ["مقدرتش أربط الرقم.", "Could not link the number."])),
      },
    );
  };
  const typeCode = (value: string) => {
    const digits = value.replace(/\D/g, "").slice(0, 6);
    setCode(digits);
    if (digits.length === 6) run(digits);
  };

  return (
    <div className="mt" data-link={row.id}>
      {row.verified ? (
        <p className="muted" style={{ fontSize: ".8rem" }}>
          {t("الرقم اتأكد خلاص. اضغط «اربط» من غير كود.", "The number is verified already. Press «Link», no code needed.")}
        </p>
      ) : (
        <div className="row row--tight">
          <button className="btn btn--sm" type="button" disabled={send.isPending} onClick={() => ask("SMS")}>
            <Icon name="message" size="sm" />
            <span>{sent ? t("ابعت الكود تاني", "Send the code again") : t("ابعت الكود برسالة", "Text me the code")}</span>
          </button>
          <button className="btn btn--sm btn--ghost" type="button" disabled={send.isPending} onClick={() => ask("VOICE")}>
            <Icon name="phone" size="sm" />
            <span>{t("بمكالمة", "By a call")}</span>
          </button>
        </div>
      )}
      <div className="row row--tight mt">
        {!row.verified && (
          <input
            className="input mono"
            style={{ maxWidth: 140, letterSpacing: ".2em" }}
            dir="ltr"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="000000"
            aria-label={t("الكود", "The code")}
            value={code}
            disabled={link.isPending}
            onChange={(event) => typeCode(event.target.value)}
          />
        )}
        <input
          className="input mono"
          style={{ maxWidth: 190 }}
          dir="ltr"
          type="password"
          inputMode="numeric"
          autoComplete="off"
          maxLength={6}
          placeholder={t("PIN (لو عليه واحد قديم)", "PIN (if it has an old one)")}
          aria-label={t("PIN التحقق بخطوتين (اختياري)", "Two-step PIN (optional)")}
          value={pin}
          disabled={link.isPending}
          onChange={(event) => setPin(event.target.value.replace(/\D/g, "").slice(0, 6))}
        />
        <button
          className="btn btn--sm btn--primary"
          type="button"
          disabled={link.isPending || (!row.verified && code.length !== 6)}
          onClick={() => run(code)}
        >
          <Icon name="check" size="sm" />
          <span>{link.isPending ? t("بيربط…", "Linking…") : t("اربط", "Link")}</span>
        </button>
      </div>
      {problem && (
        <div className="note note--high mt" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
    </div>
  );
}

/** «أرقام الواتساب»: every number on the account, what it is used for, and linking the ones that are not on the API yet. */
export function WaNumbers({ numbers, wabaSaved }: { numbers: WaNumber[]; wabaSaved: boolean }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const refresh = useRefreshWaNumbers();
  const [open, setOpen] = useState<string | null>(null);

  const reload = () =>
    refresh.mutate(undefined, {
      onSuccess: () => push({ level: "success", title: t("القايمة اتحدّثت", "The list is up to date") }),
      onError: (error) => {
        const failure = waFailure(error);
        push({
          level: "danger",
          title: failure ? (lang === "ar" ? failure.error_ar : failure.error_en) : t("مقدرتش أجيب الأرقام.", "Could not list the numbers."),
        });
      },
    });

  return (
    <div className="mt" data-numbers="">
      <div className="row row--tight">
        <div className="label">{t("أرقام الواتساب", "WhatsApp numbers")}</div>
        <div className="grow" />
        <button className="btn btn--sm btn--accent" type="button" disabled={refresh.isPending || !wabaSaved} onClick={reload}>
          <Icon name="refresh" size="sm" />
          <span>{t("حدّث القايمة", "Refresh the list")}</span>
        </button>
      </div>
      <p className="muted" style={{ fontSize: ".78rem" }}>
        {t(
          "ضيف الرقم الأول من WhatsApp Manager ← Phone numbers ← Add، وبعدين حدّث القايمة. الرقم اللي مش متربط: اطلب الكود واكتبه، والسيستم بيأكده ويربطه لوحده. بعد كده اختاره للموظف من ملفه.",
          "Add the number in WhatsApp Manager > Phone numbers > Add first, then refresh the list. For a number that is not linked: ask for the code and type it, and the system verifies and links it by itself. Then pick it for the person on their file.",
        )}
      </p>
      {!wabaSaved && (
        <div className="note note--info">
          <Icon name="info" />
          <div>{t("اكتب الـWhatsApp Business Account ID فوق واحفظ الأول.", "Save the WhatsApp Business Account ID above first.")}</div>
        </div>
      )}
      {numbers.length === 0
        ? wabaSaved && <p className="muted">{t("لسه مفيش أرقام في القايمة. اضغط «حدّث القايمة».", "No numbers listed yet. Press «Refresh the list».")}</p>
        : numbers.map((row) => (
            <div key={row.id} className="mt" data-number={row.id}>
              <div className="row row--tight">
                <b className="mono" dir="ltr">
                  {row.number || row.id}
                </b>
                {row.name && <span className="muted">{row.name}</span>}
                <span className={`badge badge--${row.connected ? "ok" : "dead"}`}>
                  <i className="badge__dot" />
                  <span>{row.connected ? t("متربط", "Linked") : t("مش متربط", "Not linked")}</span>
                </span>
                <Use row={row} />
                <div className="grow" />
                {!row.connected && (
                  <button className="btn btn--sm" type="button" aria-expanded={open === row.id} onClick={() => setOpen(open === row.id ? null : row.id)}>
                    {t("اربط الرقم", "Link this number")}
                  </button>
                )}
              </div>
              <div className="muted mono" style={{ fontSize: ".72rem" }} dir="ltr">
                ID {row.id}
              </div>
              {open === row.id && !row.connected && <LinkNumber row={row} onDone={() => setOpen(null)} />}
            </div>
          ))}
    </div>
  );
}
