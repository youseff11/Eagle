import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useChatList, useMe } from "../api/queries";
import type { ChatKind } from "../api/types";
import { ChatList } from "../components/chat/ChatList";
import { Conversation } from "../components/chat/Conversation";
import { NewGroupDialog } from "../components/chat/NewGroupDialog";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";
import { kindOfCode } from "../lib/chatCode";

const KINDS: ChatKind[] = ["clients", "groups", "staff"];

export { kindOfCode };

/** A value that follows `value` only once it has stopped changing for `delay` ms (a search box, not a request per key). */
function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

function Lists({ allowed }: { allowed: ChatKind[] }) {
  const { t } = usePreferences();
  const { code } = useParams();
  const navigate = useNavigate();
  const account = useMe().data;
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [opening, setOpening] = useState(false);
  const query = useDebounced(text.trim(), 300);

  const wanted = params.get("type");
  const fromCode = code ? kindOfCode(code) : null;
  const kind: ChatKind =
    wanted && (allowed as string[]).includes(wanted)
      ? (wanted as ChatKind)
      : fromCode && allowed.includes(fromCode)
        ? fromCode
        : allowed[0]!;

  const list = useChatList(kind, query);
  const state = list.isError && !list.data ? "error" : list.data ? "ready" : "loading";

  return (
    <div className={`cchat${code ? " is-open" : ""}`}>
      <ChatList
        kinds={allowed}
        kind={kind}
        onKind={(next) => setParams({ type: next })}
        query={text}
        onQuery={setText}
        rows={list.data?.items}
        state={state}
        activeCode={code}
        onNewGroup={account?.chats.can_create_group ? () => setOpening(true) : undefined}
      />
      {opening && account && (
        <NewGroupDialog
          me={{ name: account.user.short_name, role: account.user.role }}
          onClose={() => setOpening(false)}
          onCreated={(created) => {
            setOpening(false);
            navigate(`/chats/${created}?type=groups`);
          }}
        />
      )}
      {code ? (
        <Conversation key={code} code={code} kind={kind} allowed={allowed.includes(kindOfCode(code))} />
      ) : (
        <section className="cchat__room">
          <div className="empty cchat__blank">
            <Icon name="message" size="xl" />
            <span>{t("اختار محادثة.", "Choose a conversation.")}</span>
          </div>
        </section>
      )}
    </div>
  );
}

export function ChatsPage() {
  const { t } = usePreferences();
  const me = useMe();
  // The tabs this role has: a translator has no client tab at all, so there is nothing to click and be refused.
  const allowed = (me.data?.chats.types ?? []).filter((kind): kind is ChatKind => (KINDS as string[]).includes(kind));

  return (
    <>
      <div className="page-head">
        <h1>{t("الشات", "Chats")}</h1>
      </div>
      {me.data && allowed.length > 0 ? (
        <Lists allowed={allowed} />
      ) : (
        <div className="card">
          <div className="empty">
            <Icon name="refresh" size="xl" />
            <span>{t("بيحمّل...", "Loading...")}</span>
          </div>
        </div>
      )}
    </>
  );
}
