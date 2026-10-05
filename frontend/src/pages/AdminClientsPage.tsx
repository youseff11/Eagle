import { Loading } from "../components/Loading";
import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { useClientDeletePlan, useDeleteClients } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useAdminClients, useMe } from "../api/queries";
import type { ClientDeletePlan } from "../api/types";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/** The two steps of deleting: what would go, then the yes. Nothing is deleted before the box is ticked and the button pressed. */
function DeleteDialog({ plan, onClose, onDone }: { plan: ClientDeletePlan; onClose: () => void; onDone: (message: string) => void }) {
  const { t } = usePreferences();
  const remove = useDeleteClients();
  const [understood, setUnderstood] = useState(false);
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState("");

  const confirm = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    remove.mutate(
      { ids: plan.deletable.map((row) => row.id), password },
      {
        onSuccess: (answer) => {
          setPassword("");
          // The password the request carried is not kept in its state once it is over.
          remove.reset();
          const base = t(`اتمسح ${answer.deleted} عميل و${answer.files} ملف متخزّن. النسخة الاحتياطية اتنزّلت.`, `Deleted ${answer.deleted} client(s) and ${answer.files} stored file(s). The backup was saved.`);
          onDone(answer.blocked > 0 ? `${base} ${t(`ومااتمسحش ${answer.blocked} لأن عليهم تاسكات.`, `${answer.blocked} stayed: they have tasks.`)}` : base);
        },
        onError: (error) => {
          setPassword("");
          const detail = error instanceof ApiError ? error.detail : "";
          // A "no" from the server (4xx) came before it did anything. Anything else - a server error, a dropped connection - may
          // have come after: the clients can be gone with the backup lost on the way, so the page says it does not know.
          const refused = error instanceof ApiError && error.status >= 400 && error.status < 500;
          setProblem(
            detail ||
              (refused
                ? t("حصلت مشكلة، محدش اتمسح.", "Something went wrong, nobody was deleted.")
                : t(
                    "حصلت مشكلة وماعرفناش النتيجة. ممكن يكون اتمسح: حدّث الصفحة وراجع القايمة قبل ما تحاول تاني.",
                    "Something went wrong and the result is not known. They may be deleted: reload the page and check the list before trying again.",
                  )),
          );
          remove.reset();
        },
      },
    );
  };

  return (
    <Modal title={t("مسح عملاء", "Delete clients")} icon="alert" count={plan.deletable.length} busy={remove.isPending} wide onClose={onClose}>
      <p className="muted">{t("راجع اللي هيتمسح. مفيش رجوع، بس هتنزل نسخة احتياطية.", "Check what goes. There is no undo, but a backup is saved.")}</p>
      {plan.deletable.length > 0 ? (
        <form id="delete-clients-form" autoComplete="off" onSubmit={confirm}>
          <div className="table-wrap">
            <table className="table table--plan" data-plan="deletable">
              <thead>
                <tr>
                  <th>{t("الكود", "Code")}</th>
                  <th>{t("العميل", "Client")}</th>
                  <th>{t("رسايل", "Letters")}</th>
                  <th>{t("ملفات", "Files")}</th>
                  <th>{t("ردود اتبعتتله", "Replies sent")}</th>
                  <th>{t("غرف شات", "Chat rooms")}</th>
                </tr>
              </thead>
              <tbody>
                {plan.deletable.map((row) => (
                  <tr key={row.id} data-plan-row={row.code}>
                    <td className="mono">
                      <strong>{row.code}</strong>
                    </td>
                    <td dir="auto" className="plan__client">
                      <span>{row.name || "—"}</span>
                      <span className="muted mono" dir="ltr">{row.contact}</span>
                    </td>
                    <td className="mono">{row.letters}</td>
                    <td className="mono">{row.files}</td>
                    <td className="mono">{row.replies}</td>
                    <td className="mono">{row.rooms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="note note--warn mt">
            <Icon name="shield" />
            <div>
              {t(
                "بيتمسح العميل ورسايله وملفاته وردودنا عليه. شكاوى العملاء في الـHR وشاتات الموظفين بتفضل.",
                "The client goes with their letters, files and our replies. HR complaints and staff chats stay.",
              )}
            </div>
          </div>
          <label className="switch mt">
            <input type="checkbox" checked={understood} onChange={(event) => setUnderstood(event.target.checked)} />
            <span>{t("فاهم إن ده مسح نهائي للعملاء دول ولكل اللي معاهم.", "I understand these clients and everything with them are deleted for good.")}</span>
          </label>
          <div className="field mt">
            <label htmlFor="delete-clients-password">{t("باسورد الأدمن بتاعك", "Your admin password")}</label>
            <input
              id="delete-clients-password"
              className="input"
              type="password"
              autoComplete="current-password"
              style={{ maxWidth: 320 }}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
        </form>
      ) : (
        <div className="empty">
          <Icon name="archive" size="xl" />
          <span>{t("مفيش عميل من اللي اخترتهم ينفع يتمسح.", "None of the chosen clients can be deleted.")}</span>
        </div>
      )}

      {plan.blocked.length > 0 && (
        <div className="mt" data-plan="blocked">
          <h4>
            {t("مش هيتمسحوا", "Cannot be deleted")} <b className="mono">{plan.blocked.length}</b>
          </h4>
          {plan.blocked.map((row) => (
            <div className="kv" key={row.id}>
              <span className="mono">{row.code}</span>
              <b>{row.blocked}</b>
            </div>
          ))}
          <p className="muted" style={{ fontSize: ".85rem" }}>
            {t(
              "التاسك بيقرا ملفاته الأصلية من رسايل العميل، فمسح العميل هيشيلها من الشغل الجاري. يتمسحوا بعد ما التاسكات تتمسح.",
              "A task reads its original files off the client's letters, so deleting the client would take them out from under live work. They can go once the tasks are gone.",
            )}
          </p>
        </div>
      )}

      {problem && (
        <div className="note note--high mt" role="alert">
          <Icon name="alert" />
          <div>{problem}</div>
        </div>
      )}
      <div className="row mt">
        {plan.deletable.length > 0 && (
          <button className="btn btn--danger" type="submit" form="delete-clients-form" disabled={!understood || password === "" || remove.isPending}>
            <Icon name="trash" size="sm" />
            <span>{t("امسح العملاء دول", "Delete these clients")}</span>
          </button>
        )}
        <button className="btn btn--ghost" type="button" disabled={remove.isPending} onClick={onClose}>
          {t("رجوع", "Back")}
        </button>
      </div>
    </Modal>
  );
}

/**
 * The client records: every client with the real name, company, numbers and addresses (admin only). A search narrows
 * them, one filter lists the no-reply addresses that are not clients, and ticked clients can be deleted in two steps.
 */
export function AdminClientsPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const q = (params.get("q") ?? "").trim();
  const show = params.get("show") === "robots" ? "robots" : "";
  const [box, setBox] = useState(q);
  const [picked, setPicked] = useState<number[]>([]);
  const [plan, setPlan] = useState<ClientDeletePlan | null>(null);
  const [planProblem, setPlanProblem] = useState("");
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminClients(q, show, allowed);
  const asking = useClientDeletePlan();

  // The address is the truth about the search: a link to a filter changes the box too.
  useEffect(() => setBox(q), [q]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;

  const link = (nextShow: string) => {
    const next = new URLSearchParams();
    if (q) next.set("q", q);
    if (nextShow) next.set("show", nextShow);
    const text = next.toString();
    return `/admin/clients${text ? `?${text}` : ""}`;
  };
  const search = (event: FormEvent) => {
    event.preventDefault();
    const next = new URLSearchParams();
    if (box.trim()) next.set("q", box.trim());
    if (show) next.set("show", show);
    setPicked([]);
    setParams(next);
  };
  const ids = data?.clients.map((row) => row.id) ?? [];
  const all = ids.length > 0 && ids.every((id) => picked.includes(id));
  const ask = () => {
    setPlanProblem("");
    asking.mutate(picked, {
      onSuccess: setPlan,
      onError: () => setPlanProblem(t("حصلت مشكلة، ماتعرفش اللي هيتمسح.", "Something went wrong, could not work out what would go.")),
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("بيانات العملاء", "Client records")}</h1>
        <span className="page-head__sub">{t("الصفحة دي للأدمن بس — فيها الأسماء والأرقام.", "Admin only - real names and numbers.")}</span>
        <div className="grow" />
        <Link className="btn btn--primary" to="/admin/clients/new">
          <Icon name="plus" size="sm" />
          <span>{t("عميل جديد", "New client")}</span>
        </Link>
      </div>

      <div className="card card--flat" style={{ marginBottom: 14 }}>
        <form className="row row--tight" style={{ flexWrap: "wrap" }} onSubmit={search} role="search">
          <input
            className="input grow"
            type="search"
            style={{ minWidth: "12rem" }}
            maxLength={200}
            value={box}
            onChange={(event) => setBox(event.target.value)}
            aria-label={t("بحث", "Search")}
            placeholder={t("دوّر بالكود أو الاسم أو التليفون أو الإيميل", "Search by code, name, phone or e-mail")}
          />
          <button className="btn" type="submit">
            <Icon name="search" size="sm" />
            <span>{t("بحث", "Search")}</span>
          </button>
        </form>
        <div className="tabs mt" style={{ marginBottom: 0 }}>
          <Link className={`tab${show ? "" : " is-active"}`} to={link("")}>
            <span>{t("الكل", "All")}</span> <b className="mono">{data?.all_count ?? 0}</b>
          </Link>
          <Link className={`tab${show ? " is-active" : ""}`} to={link("robots")}>
            <span>{t("ميلات وهمية (noreply)", "Robot addresses (noreply)")}</span> <b className="mono">{data?.robots_count ?? 0}</b>
          </Link>
          {data && (
            <span className="muted" style={{ fontSize: ".8rem", alignSelf: "center" }}>
              {t("بيظهر هنا", "Showing")} <b className="mono">{data.clients.length}</b>
              {data.shown > data.clients.length && (
                <>
                  {" "}
                  {t("من", "of")} <b className="mono">{data.shown}</b>
                </>
              )}
            </span>
          )}
        </div>
        {show && (
          <p className="muted mt" style={{ fontSize: ".85rem" }}>
            {t(
              "دول عناوين روبوتات (زي no-reply) مش عملاء. حدّدهم كلهم من المربع اللي فوق الجدول وامسحهم. الميلات الجاية من عناوين زي دي بقت بتتجاهل ومابتعملش عملاء.",
              "These are robot addresses (like no-reply), not clients. Tick them all from the box above the table and delete. Mail from addresses like these is now ignored and no longer makes clients.",
            )}
          </p>
        )}
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="contact" />
          <h3>{t("العملاء", "Clients")}</h3>
          <div className="grow" />
          <span className="muted" style={{ fontSize: ".85rem" }}>
            {t("المحدّد:", "Selected:")} <b className="mono" data-selected-count>{picked.length}</b>
          </span>
          <button className="btn btn--danger btn--sm" type="button" disabled={picked.length === 0 || asking.isPending} onClick={ask}>
            <Icon name="trash" size="sm" />
            <span>{t("امسح المحدّد", "Delete selected")}</span>
          </button>
        </div>
        {planProblem && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{planProblem}</div>
          </div>
        )}

        {data ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: "2.2rem" }}>
                    <input
                      type="checkbox"
                      aria-label={t("حدّد الكل", "Select all")}
                      checked={all}
                      onChange={(event) => setPicked(event.target.checked ? ids : [])}
                    />
                  </th>
                  <th>{t("الكود", "Code")}</th>
                  <th>{t("الاسم", "Name")}</th>
                  <th>{t("الشركة", "Company")}</th>
                  <th>{t("التليفون", "Phone")}</th>
                  <th>{t("الإيميل", "Email")}</th>
                  <th>{t("نشط", "Active")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.clients.map((row) => (
                  <tr key={row.id} data-client={row.code}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={row.code}
                        checked={picked.includes(row.id)}
                        onChange={(event) => setPicked(event.target.checked ? [...picked, row.id] : picked.filter((id) => id !== row.id))}
                      />
                    </td>
                    <td className="mono">
                      <strong>{row.code}</strong>
                    </td>
                    <td>{row.name || "—"}</td>
                    <td>{row.company || "—"}</td>
                    <td className="mono" dir="ltr">
                      {row.phone || "—"}
                      {row.more_phones > 0 && <span className="chip chip--sm">+{row.more_phones}</span>}
                    </td>
                    <td className="mono" dir="ltr">
                      {row.email || "—"}
                      {row.more_emails > 0 && <span className="chip chip--sm">+{row.more_emails}</span>}
                    </td>
                    <td>
                      <span className={`dot dot--${row.active ? "on" : "off"}`} title={row.active ? t("نشط", "Active") : t("موقوف", "Switched off")} />
                    </td>
                    <td>
                      <div className="row row--tight">
                        <Link className="btn btn--sm" to={`/clients/${encodeURIComponent(row.code)}`}>
                          {t("ملف", "Profile")}
                        </Link>
                        <Link className="btn btn--sm" to={`/admin/clients/${encodeURIComponent(row.code)}/edit`}>
                          {t("تعديل", "Edit")}
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
                {data.clients.length === 0 && (
                  <tr>
                    <td colSpan={8} className="empty">
                      <Icon name="archive" size="xl" />
                      <span>{t("مفيش عملاء.", "No clients.")}</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : query.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <Loading className="empty" />
        )}
      </div>

      {plan && (
        <DeleteDialog
          plan={plan}
          onClose={() => setPlan(null)}
          onDone={(message) => {
            setPlan(null);
            setPicked([]);
            push({ level: "success", title: message, sticky: true });
          }}
        />
      )}
    </>
  );
}
