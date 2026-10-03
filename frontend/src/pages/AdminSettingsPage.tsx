import { useMemo, useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import { formErrors, useConnectionTest, useGoogleDisconnect, useGoogleSync, useSaveSettings } from "../api/adminActions";
import { useAdminSettings, useMe } from "../api/queries";
import type { AdminSettings, ConnectionReport, FormErrors, FormField } from "../api/types";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

type Edits = ReturnType<typeof useFormEdits>;

function Badge({ ok, yes, no }: { ok: boolean; yes: [string, string]; no: [string, string] }) {
  const { t } = usePreferences();
  return (
    <span className={`badge badge--${ok ? "ok" : "dead"}`}>
      <i className="badge__dot" />
      <span>{t(...(ok ? yes : no))}</span>
    </span>
  );
}

/** What a "save & test" gave back, in words (`renderReport` on the classic page). */
function Report({ report, okLabel }: { report: ConnectionReport; okLabel: string }) {
  const { t, lang } = usePreferences();
  if (!report.ok) {
    return (
      <div className="note note--high" role="alert">
        <Icon name="alert" />
        <div>{(lang === "ar" ? report.error_ar || report.error_en : report.error_en || report.error_ar) ?? ""}</div>
      </div>
    );
  }
  const detail = [
    report.number,
    report.name,
    report.quality ? `quality: ${report.quality}` : "",
    report.host,
    report.user,
    report.sent ? t("واتبعت رسالة اختبار", "test message sent") : "",
  ].filter(Boolean);
  return (
    <div className="note note--ok" role="status">
      <Icon name="check-circle" />
      <div>
        <strong>{okLabel}</strong>
        {detail.length > 0 && <div className="muted mono">{detail.join(" · ")}</div>}
      </div>
    </div>
  );
}

/**
 * «احفظ واختبر الاتصال»: the test reads what is saved, not what is on the page, so anything changed is saved first - and a
 * save that is refused stops the test and says which box is wrong.
 */
function ConnectionTest({
  kind,
  id,
  placeholder,
  okLabel,
  saveFirst,
}: {
  kind: "whatsapp" | "email";
  id: string;
  placeholder: string;
  okLabel: string;
  saveFirst: () => Promise<{ ok: boolean; fields: string[] }>;
}) {
  const { t } = usePreferences();
  const test = useConnectionTest(kind);
  const [to, setTo] = useState("");
  const [phase, setPhase] = useState<"idle" | "saving" | "testing">("idle");
  const [report, setReport] = useState<ConnectionReport | null>(null);
  const [problem, setProblem] = useState("");

  const run = async () => {
    setReport(null);
    setProblem("");
    setPhase("saving");
    const saved = await saveFirst();
    if (!saved.ok) {
      setPhase("idle");
      setProblem(`${t("الحفظ فشل — فيه حقل غلط: ", "Save failed - invalid field: ")}${saved.fields.join(", ") || t("راجع الحقول.", "check the fields.")}`);
      return;
    }
    setPhase("testing");
    test.mutate(to, {
      onSuccess: (answer) => setReport(answer),
      onError: () => setProblem(t("مشكلة في الاتصال بالسيرفر.", "Could not reach the server.")),
      onSettled: () => setPhase("idle"),
    });
  };

  return (
    <>
      <div className="row row--tight mt">
        <input
          className="input"
          id={id}
          style={{ maxWidth: 240 }}
          dir="ltr"
          placeholder={placeholder}
          aria-label={placeholder}
          value={to}
          onChange={(event) => setTo(event.target.value)}
        />
        <button className="btn btn--accent" type="button" disabled={phase !== "idle"} onClick={() => void run()}>
          <Icon name="refresh" size="sm" />
          <span>{t("احفظ واختبر الاتصال", "Save & test connection")}</span>
        </button>
        {kind === "whatsapp" && <span className="muted" style={{ fontSize: ".78rem" }}>{t("الزرار بيحفظ الأول لوحده.", "The button saves first, automatically.")}</span>}
      </div>
      <div className="mt" data-result={kind}>
        {phase === "saving" && <div className="muted" style={{ fontSize: ".8rem" }}>{t("بيحفظ الإعدادات…", "Saving settings…")}</div>}
        {phase === "testing" && <div className="muted" style={{ fontSize: ".8rem" }}>{t("بيجرب الاتصال…", "Testing the connection…")}</div>}
        {report && <Report report={report} okLabel={okLabel} />}
        {problem && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{problem}</div>
          </div>
        )}
      </div>
    </>
  );
}

/** The alias list from Google: linked or not, the last sync, the redirect address to register, and the three buttons. */
function GoogleControls({ data }: { data: AdminSettings }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const sync = useGoogleSync();
  const disconnect = useGoogleDisconnect();
  const { status, urls } = data;
  const when = status.google_sync_at ? (lang === "ar" ? status.google_sync_at.ar : status.google_sync_at.en) : "";

  const runSync = () =>
    sync.mutate(undefined, {
      onSuccess: (answer) => {
        if (answer.error) return push({ level: "danger", title: answer.error });
        const parts = [
          answer.added.length ? `${t("اتضاف:", "Added:")} ${answer.added.join(", ")}` : "",
          answer.removed.length ? `${t("اتشال:", "Removed:")} ${answer.removed.join(", ")}` : "",
          answer.released.length ? `${t("اتشال العنوان من:", "Taken off:")} ${answer.released.join(", ")}` : "",
        ].filter(Boolean);
        push({ level: "success", title: parts.join(" · ") || t("القايمة زي Google بالظبط", "The list is exactly Google's") });
      },
      onError: () => push({ level: "danger", title: t("حصلت مشكلة في المزامنة.", "The sync failed.") }),
    });
  const runDisconnect = () =>
    disconnect.mutate(undefined, {
      onSuccess: () => push({ level: "success", title: t("اتفصل", "Disconnected") }),
      onError: () => push({ level: "danger", title: t("حصلت مشكلة، ماتفصلش.", "Something went wrong, it was not disconnected.") }),
    });

  return (
    <>
      <div className="row row--tight">
        <Badge ok={status.google_connected} yes={["مربوط", "Linked"]} no={["مش مربوط", "Not linked"]} />
        {when && (
          <span className="muted" style={{ fontSize: ".78rem" }}>
            {t("آخر مزامنة:", "Last sync:")} <span className="mono" dir="ltr">{when}</span>
          </span>
        )}
      </div>
      {status.google_sync_error && (
        <p className="errorlist mt" style={{ fontSize: ".8rem" }}>
          {status.google_sync_error}
        </p>
      )}
      <div className="field mt">
        <label htmlFor="settings-redirect">Redirect URI</label>
        <input id="settings-redirect" className="input mono" dir="ltr" readOnly value={urls.google_redirect} onClick={(event) => event.currentTarget.select()} />
        <span className="helptext">{t("انسخه في Authorized redirect URIs في Google Cloud.", "Paste it into Authorized redirect URIs in Google Cloud.")}</span>
      </div>
      <div className="row row--tight mt">
        {status.google_configured ? (
          <a className="btn" href={urls.google_connect}>
            {status.google_connected ? t("اربط تاني", "Reconnect") : t("اربط Google", "Connect Google")}
          </a>
        ) : (
          <span className="muted" style={{ fontSize: ".78rem" }}>
            {t("اكتب Client ID وClient Secret واحفظ، وبعدين اربط.", "Enter the Client ID and Secret, save, then connect.")}
          </span>
        )}
        {status.google_connected && (
          <>
            <button className="btn btn--accent" type="button" disabled={sync.isPending} onClick={runSync}>
              <Icon name="refresh" size="sm" />
              <span>{t("حدّث دلوقتي", "Sync now")}</span>
            </button>
            <button className="btn" type="button" disabled={disconnect.isPending} onClick={runDisconnect}>
              {t("افصل", "Disconnect")}
            </button>
          </>
        )}
      </div>
    </>
  );
}

/** The switches that send each screen's people to the new interface: by role, or by name to try one person first. */
function NewUiCard({ data, edits, errors }: { data: AdminSettings; edits: Edits; errors: FormErrors }) {
  const { t, lang } = usePreferences();
  const byName = new Map(data.fields.map((field) => [field.name, field]));
  return (
    <>
      <p className="muted" style={{ fontSize: ".84rem" }}>
        {t(
          "كل شاشة بتتنقل للواجهة الجديدة لوحدها. اللي معلّم عليهم بيتحوّلوا للنسخة الجديدة، والباقي يفضلوا على القديمة. شيل العلامة وهيرجعوا للقديمة فورًا من غير ما حد يعمل حاجة.",
          "Each screen moves to the new interface on its own. The people ticked are sent to the new version and everybody else stays on the classic one. Untick and they are back on the classic page at once.",
        )}
      </p>
      {data.newui.map((row) => {
        const roles = byName.get(row.roles);
        const users = byName.get(row.users);
        if (!roles) return null;
        const list = (field: FormField) => (
          <div className="row row--tight" style={{ flexWrap: "wrap" }}>
            {(field.choices ?? []).map((choice) => {
              const chosen = edits.valueOf(field);
              const on = Array.isArray(chosen) && chosen.includes(choice.value);
              return (
                <label key={choice.value} className="chip" style={{ cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={(event) => {
                      const now = Array.isArray(chosen) ? chosen : [];
                      edits.set(field.name, event.target.checked ? [...now, choice.value] : now.filter((item) => item !== choice.value));
                    }}
                  />
                  <span>{choice.label}</span>
                </label>
              );
            })}
          </div>
        );
        const problems = [...(errors[row.roles] ?? []), ...(errors[row.users] ?? [])];
        return (
          <div className="field" key={row.key} data-screen={row.key}>
            <label>{lang === "ar" ? row.ar : row.en}</label>
            {list(roles)}
            {users && (users.choices ?? []).length > 0 && (
              <>
                <label className="muted" style={{ fontSize: ".84rem" }}>
                  {t("أو ناس بالاسم (تجربة على واحد قبل الدور كله)", "Or people one by one (try it on one before the whole role)")}
                </label>
                {list(users)}
              </>
            )}
            {problems.length > 0 && (
              <ul className="errorlist" role="alert">
                {problems.map((message, index) => (
                  <li key={index}>{message}</li>
                ))}
              </ul>
            )}
            <span className="helptext">{t("الصفحة القديمة بتفتح دايمًا لو ضفت ?classic=1 آخر العنوان.", "The classic page always opens if you add ?classic=1 to its address.")}</span>
          </div>
        );
      })}
    </>
  );
}

/**
 * The settings: the AI check, the workflow rules, which screens are on the new interface, WhatsApp and the mail.
 *
 * It draws what the server describes - a secret is only ever "saved" or not, so a box for one starts empty and stays empty
 * unless something is typed (or the saved value is explicitly cleared) - and sends only what was changed. This is also the page
 * that holds the switches for the new interface: the classic one stays reachable with `?classic=1` in case this one breaks.
 */
export function AdminSettingsPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminSettings(allowed);
  const data = query.data;
  const edits = useFormEdits(data?.fields);
  const save = useSaveSettings();
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);
  const byName = useMemo(() => new Map((data?.fields ?? []).map((field) => [field.name, field])), [data]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) {
    return query.isError ? (
      <div className="card empty" role="alert">
        <Icon name="alert" size="xl" />
        <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
      </div>
    ) : (
      <div className="card empty">
        <Icon name="refresh" size="xl" />
        <span>{t("بيحمّل...", "Loading...")}</span>
      </div>
    );
  }

  /** Save what changed; nothing changed is a save that went through. Says which boxes were refused when it did not. */
  const saveNow = (announce: boolean) =>
    new Promise<{ ok: boolean; fields: string[] }>((resolve) => {
      setErrors({});
      setFailed(false);
      if (!edits.dirty) return resolve({ ok: true, fields: [] });
      save.mutate(edits.edited, {
        onSuccess: () => {
          edits.reset();
          // What was typed (a secret among it) is not kept in the request's own state once it is saved.
          save.reset();
          if (announce) push({ level: "success", title: t("اتحفظ", "Saved") });
          resolve({ ok: true, fields: [] });
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setFailed(true);
          resolve({ ok: false, fields: found ? Object.keys(found) : [] });
        },
      });
    });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void saveNow(true);
  };
  const pick = (names: string[]) => names.map((name) => byName.get(name)).filter((field): field is FormField => field !== undefined);
  const copy = (text: string) => {
    void navigator.clipboard?.writeText(text).then(() => push({ level: "success", title: t("اتنسخ", "Copied") }));
  };
  // The messages that belong to no field are shown once at the top, not again under every group.
  const lone: FormErrors = Object.fromEntries(Object.entries(errors).filter(([name]) => name !== "__all__"));

  return (
    <>
      <div className="page-head">
        <h1>{t("الإعدادات", "Settings")}</h1>
      </div>

      <form onSubmit={submit} style={{ maxWidth: 920 }} id="settingsForm">
        {errors.__all__ && (
          <ul className="errorlist" role="alert">
            {errors.__all__.map((message, index) => (
              <li key={index}>{message}</li>
            ))}
          </ul>
        )}

        {data.sections.map((section) => (
          <div className="card" id={`s-${section.key}`} key={section.key} data-section={section.key}>
            <div className="card__head">
              <Icon name={section.icon} />
              <h3>{t(section.ar, section.en)}</h3>
              {section.key === "whatsapp" && (
                <>
                  <div className="grow" />
                  <Badge ok={data.status.whatsapp_saved} yes={["المفاتيح محفوظة", "Keys saved"]} no={["المفاتيح لسه متحفظتش", "Keys not saved yet"]} />
                </>
              )}
              {section.key === "email" && (
                <>
                  <div className="grow" />
                  <Badge ok={data.status.email_saved} yes={["محفوظ", "Saved"]} no={["لسه متحفظش", "Not saved yet"]} />
                </>
              )}
            </div>
            {section.note_ar && <p className="muted" style={{ fontSize: ".84rem" }}>{t(section.note_ar, section.note_en ?? section.note_ar)}</p>}

            {section.key === "newui" && <NewUiCard data={data} edits={edits} errors={errors} />}

            {section.key === "whatsapp" && (
              <>
                <div className="label">{t("حط الرابط ده في Meta ← Configuration ← Callback URL", "Put this in Meta -> Configuration -> Callback URL")}</div>
                <div className="copy-row">
                  <code className="mono grow" id="whUrl">{data.urls.webhook}</code>
                  <button className="btn btn--sm" type="button" onClick={() => copy(data.urls.webhook)}>
                    {t("نسخ", "Copy")}
                  </button>
                </div>
                {!data.status.webhook_signed && (
                  <div className="note note--warn mt" data-warning="unsigned">
                    <Icon name="shield" />
                    <div>
                      {t(
                        "الـApp secret مش محفوظ: الويب هوك مش بيتحقق من توقيع Meta، فأي حد يعرف رابطه يقدر يبعت رسالة شكلها من Meta وتتسجل كأنها من عميل. احفظه.",
                        "The App secret is not saved: the webhook cannot check Meta's signature, so anybody who knows its address can send a message that looks like Meta's and have it recorded as a client's. Save it.",
                      )}
                    </div>
                  </div>
                )}
                {!data.status.webhook_secret_set && (
                  <div className="note note--warn mt" data-warning="open">
                    <Icon name="shield" />
                    <div>
                      {t(
                        "سر الويب هوك مش متحدد: الويب هوك البسيط (غير بتاع Meta) بيقبل أي طلب من غير سر.",
                        "The webhook secret is not set: the simple (non-Meta) webhook accepts any request without a secret.",
                      )}
                    </div>
                  </div>
                )}
                {data.urls.is_local ? (
                  <div className="note note--high mt">
                    <Icon name="alert" />
                    <div>
                      {t(
                        "الرابط ده محلي — سيرفرات Meta مش هتعرف توصله. شغّل نفق زي ngrok (الأمر: ngrok http 8000) وحط الرابط بتاعه المنتهي بـ /webhooks/whatsapp/ في Meta.",
                        "This address is local - Meta cannot reach it. Run a tunnel (ngrok http 8000) and register that public URL ending in /webhooks/whatsapp/ instead.",
                      )}
                    </div>
                  </div>
                ) : (
                  !data.urls.is_https && (
                    <div className="note note--warn mt">
                      <Icon name="alert" />
                      <div>{t("Meta بتقبل HTTPS بس.", "Meta only accepts HTTPS callback URLs.")}</div>
                    </div>
                  )
                )}
              </>
            )}

            {section.groups.map((group, index) => {
              const fields = pick(group.fields);
              const google = group.fields.includes("google_client_id");
              return (
                <div key={index} data-group={group.fields[0]}>
                  {group.ar && (
                    <div className="label mt">{t(group.ar, group.en ?? group.ar)}</div>
                  )}
                  {group.note_ar && <p className="muted" style={{ fontSize: ".78rem" }}>{t(group.note_ar, group.note_en ?? group.note_ar)}</p>}
                  {google && (
                    <p className="muted" style={{ fontSize: ".78rem" }}>
                      {t(
                        "أي alias تضيفه أو تمسحه في Google Admin بيظهر أو يختفي من القايمة لوحده. لو عنوان اتمسح وكان متحدد لموظف، بيتشال منه وميلاته تروح للأدمن.",
                        "Any alias added or deleted in Google Admin appears in or leaves the list by itself. A deleted address held by someone is taken off them and their mail goes to the admin.",
                      )}
                    </p>
                  )}
                  <DjangoForm fields={fields} edits={edits} errors={lone} prefix="settings" />
                  {group.fields.includes("mail_aliases") && data.status.google_connected && (
                    <span className="helptext">{t("مربوطة بـ Google: القايمة بتتحدّث لوحدها ومش بتتعدّل من هنا.", "Linked to Google: the list updates itself and is not edited here.")}</span>
                  )}
                  {google && <GoogleControls data={data} />}
                </div>
              );
            })}

            {section.key === "whatsapp" && (
              <ConnectionTest
                kind="whatsapp"
                id="waTestTo"
                placeholder={t("رقم للتجربة (اختياري) 2010…", "Test number (optional) 2010…")}
                okLabel={t("الاتصال بواتساب شغال", "WhatsApp connection is working")}
                saveFirst={() => saveNow(false)}
              />
            )}
            {section.key === "email" && (
              <ConnectionTest
                kind="email"
                id="mailTestTo"
                placeholder={t("إيميل للتجربة (اختياري)", "Test address (optional)")}
                okLabel={t("الاتصال بالإيميل شغال", "E-mail connection is working")}
                saveFirst={() => saveNow(false)}
              />
            )}
          </div>
        ))}

        {failed && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{t("حصلت مشكلة، ماتحفظش حاجة.", "Something went wrong, nothing was saved.")}</div>
          </div>
        )}
        {Object.keys(errors).length > 0 && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{t("اتحفظش حاجة: راجع الحقول اللي جنبها خطأ.", "Nothing was saved: check the fields with an error beside them.")}</div>
          </div>
        )}
        <button className="btn btn--primary" type="submit" disabled={save.isPending || !edits.dirty}>
          <Icon name="check" size="sm" />
          <span>{t("حفظ الإعدادات", "Save settings")}</span>
        </button>
      </form>
    </>
  );
}
