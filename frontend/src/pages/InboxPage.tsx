import { Loading } from "../components/Loading";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { useFetchMail } from "../api/mailActions";
import { useMailThreads, useMe } from "../api/queries";
import type { MailListResponse, MailRow } from "../api/types";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

/** The filters of the list, as the server knows them: anything else in the address is not sent. */
const STATES = ["unclaimed", "mine", "notask"];

/** The address of a conversation, carrying the list's filters so that "back" lands where the person was. */
export function threadPath(id: number, state: string, query: string): string {
  const params = new URLSearchParams();
  if (state) params.set("state", state);
  if (query) params.set("q", query);
  const text = params.toString();
  return `/inbox/thread/${id}${text ? `?${text}` : ""}`;
}

function Notes({ data }: { data: MailListResponse }) {
  const { t } = usePreferences();
  const { mail } = data;
  const me = useMe();
  return (
    <>
      {!mail.configured ? (
        <div className="note note--warn mt">
          <Icon name="alert" />
          <div>
            <strong>{t("صندوق البريد مش متظبّط", "The mailbox is not configured")}</strong>
            <div>
              {t(
                "من غير بيانات IMAP في الإعدادات مفيش ميل هيوصل الصفحة دي أصلًا.",
                "Without the IMAP details under Settings no e-mail ever reaches this page.",
              )}
            </div>
          </div>
        </div>
      ) : mail.last_error ? (
        <div className="note note--high mt" role="alert">
          <Icon name="alert" />
          <div>
            <strong>{t("آخر محاولة جلب فشلت", "The last fetch failed")}</strong>
            <div>{mail.last_error}</div>
          </div>
        </div>
      ) : (
        mail.last_fetch && (
          <div className="note note--info mt">
            <Icon name="clock" />
            <div>
              <span>{t("آخر جلب:", "Last fetch:")}</span> <span className="mono">{t(mail.last_fetch.ar, mail.last_fetch.en)}</span>
              {" · "}
              <span>{t("جاب", "brought")}</span> <strong className="mono">{mail.last_count}</strong>
            </div>
          </div>
        )
      )}
      {me.data?.user.is_admin && data.blocked > 0 && (
        <div className="note note--warn mt">
          <Icon name="shield" />
          <div>
            <span>{t("ميلات محجوبة عن الأوبريشن:", "Mail hidden from Operation (rate keyword):")}</span>{" "}
            <strong className="mono">{data.blocked}</strong>
          </div>
        </div>
      )}
    </>
  );
}

function Row({ row, state, query }: { row: MailRow; state: string; query: string }) {
  const { t } = usePreferences();
  return (
    <article
      className={`mail mail--thread${row.unread ? " is-unread" : ""}${row.blocked ? " is-blocked" : ""}`}
      data-thread={row.key}
    >
      <Link className="mail__row" to={threadPath(row.id, state, query)} title={t("افتح المحادثة", "Open the conversation")}>
        <span className="avatar avatar--brand mail__avatar">
          {row.code ? row.code.slice(3) : <Icon name="mail" size="sm" />}
        </span>
        <span className="mail__body">
          <span className="mail__top">
            <b className="mail__from">{row.from || t("مرسل غير معروف", "Unknown sender")}</b>
            {row.count > 1 && (
              <span className="mail__count mono" title={t("عدد الميلات في المحادثة", "Letters in this conversation")}>
                {row.count}
              </span>
            )}
            {row.at && <span className="mail__time mono">{t(row.at.ar, row.at.en)}</span>}
          </span>
          <span className="mail__subject">{row.subject || <span className="muted">{t("(من غير عنوان)", "(no subject)")}</span>}</span>
          <span className="mail__snippet">{row.snippet}</span>
          <span className="mail__tags">
            {row.answered && (
              <span className="chip chip--sm chip--replied">
                <Icon name="reply" size="sm" />
                <span>{t("اتردّ عليها", "Replied")}</span>
              </span>
            )}
            {row.blocked && (
              <span className="badge badge--dead">
                <i className="badge__dot" />
                <span>{t("محجوبة — سعر", "Hidden — rate")}</span>
              </span>
            )}
            {row.tasks.map((code) => (
              <span key={code} className="badge badge--ok mono">
                {code}
              </span>
            ))}
            {row.files > 0 && (
              <span className="chip chip--sm">
                <Icon name="paperclip" size="sm" />
                {row.files}
              </span>
            )}
            {row.claimers.length > 0
              ? row.claimers.map((name) => (
                  <span key={name} className="chip chip--sm">
                    <Icon name="user-check" size="sm" />
                    {name}
                  </span>
                ))
              : !row.answered && (
                  <span className="chip chip--sm chip--open">
                    <Icon name="user" size="sm" />
                    <span>{t("محدش استلمها", "Nobody claimed it")}</span>
                  </span>
                )}
          </span>
        </span>
        <span className="mail__chev mail__chev--go">
          <Icon name="chevron-down" size="sm" />
        </span>
      </Link>
    </article>
  );
}

/** The search and the filter. The address holds both, so a reload, a link and the way back from a conversation keep them. */
function Filters({ state, query, onChange }: { state: string; query: string; onChange: (state: string, query: string) => void }) {
  const { t } = usePreferences();
  const [text, setText] = useState(query);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onChange(state, text.trim());
  };
  return (
    <form className="row" onSubmit={submit} role="search">
      <div className="field-icon grow" style={{ margin: 0 }}>
        <Icon name="search" className="ic--lead" />
        <input
          className="input"
          name="q"
          value={text}
          maxLength={200}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("ابحث في العنوان أو نص الميل أو كود العميل…", "Search the subject, the text or the client code…")}
          aria-label={t("بحث", "Search")}
        />
      </div>
      <select
        className="input"
        style={{ maxWidth: 210 }}
        value={state}
        onChange={(event) => onChange(event.target.value, text.trim())}
        aria-label={t("الفلتر", "Filter")}
      >
        <option value="">{t("كل الميلات", "All mail")}</option>
        <option value="unclaimed">{t("محدش استلمها", "Unclaimed")}</option>
        <option value="mine">{t("اللي أنا استلمتها", "Claimed by me")}</option>
        <option value="notask">{t("من غير تاسك", "Without a task")}</option>
      </select>
      <button className="btn" type="submit">
        {t("بحث", "Search")}
      </button>
    </form>
  );
}

/** The mailbox: one row per conversation, newest first - the operation's and the Sales' own, and the admin's all. */
export function InboxPage() {
  const { t } = usePreferences();
  const me = useMe();
  const [params, setParams] = useSearchParams();
  // The address is the person's to type: only a filter we know of, and a search of a sensible length, go to the server.
  const askedState = params.get("state") ?? "";
  const state = STATES.includes(askedState) ? askedState : "";
  const asked = (params.get("q") ?? "").trim();
  const query = asked.length <= 200 ? asked : "";
  const role = me.data?.user.role;
  // The same people the server lets in (`api_role_required`: the operation and the Sales, and the admin).
  const allowed = me.data !== undefined && (role === "operation" || role === "sales" || me.data.user.is_admin);
  const list = useMailThreads(state, query, allowed);
  const fetchNow = useFetchMail();

  if (me.data && !allowed) return <Navigate to="/" replace />;

  const data = list.data;
  // Polling the mailbox and making tasks are the operation's (and the admin's): the Sales' mail arrives on its own.
  const operation = role !== "sales";
  const change = (nextState: string, nextQuery: string) => {
    const next: Record<string, string> = {};
    if (nextState) next.state = nextState;
    if (nextQuery) next.q = nextQuery;
    setParams(next);
  };
  const fetched = fetchNow.data;
  const fetchError =
    fetchNow.error instanceof ApiError ? ((fetchNow.error.payload as { error?: string } | null)?.error ?? "") : "";

  return (
    <>
      <div className="page-head">
        <h1>{t("ميلات واردة", "Incoming mail")}</h1>
        {data && data.unseen > 0 && (
          <span className="badge badge--new mono" title={t("محادثات لسه مفتحتهاش", "Conversations you have not opened")}>
            {data.unseen}
          </span>
        )}
        {data && data.unclaimed > 0 && (
          <span className="badge badge--wait" title={t("محادثات محدش استلمها", "Conversations nobody has claimed")}>
            <Icon name="user" size="sm" />
            <span className="mono">{data.unclaimed}</span> <span>{t("محدش استلمها", "unclaimed")}</span>
          </span>
        )}
        <span className="page-head__sub">{t("الميلات بس. رسايل الواتساب في شات العملاء.", "E-mail only. WhatsApp lives in the client chat.")}</span>
        <div className="grow" />
        {operation && (
          <button className="btn" type="button" disabled={fetchNow.isPending} onClick={() => fetchNow.mutate()}>
            <Icon name="refresh" size="sm" />
            <span>{t("جيب الميلات دلوقتي", "Fetch mail now")}</span>
          </button>
        )}
        {operation && (
          <Link className="btn btn--primary" to="/tasks/new">
            <Icon name="plus" size="sm" />
            <span>{t("تاسك جديدة", "New task")}</span>
          </Link>
        )}
      </div>

      {fetched?.ok && (
        <div className="note note--ok" role="status" style={{ marginBottom: 14 }}>
          <Icon name="check-circle" />
          <div>{t(`اتجاب ${fetched.created} ميل جديد.`, `${fetched.created} new letter(s) brought in.`)}</div>
        </div>
      )}
      {fetchNow.isError && (
        <div className="note note--high" role="alert" style={{ marginBottom: 14 }}>
          <Icon name="alert" />
          <div>{fetchError || t("مقدرتش أجيب الميلات.", "Could not fetch the mail.")}</div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 14 }}>
        <Filters key={query} state={state} query={query} onChange={change} />
        {data && <Notes data={data} />}
      </div>

      {data ? (
        <div className="mail-list" id="inboxList">
          {data.threads.length === 0 && (
            <div className="card empty">
              <Icon name="mail" size="xl" />
              <span>{t("مفيش ميلات هنا دلوقتي.", "No mail here yet.")}</span>
            </div>
          )}
          {data.threads.map((row) => (
            <Row key={row.key} row={row} state={state} query={query} />
          ))}
        </div>
      ) : list.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <Loading className="card empty" />
      )}
    </>
  );
}
