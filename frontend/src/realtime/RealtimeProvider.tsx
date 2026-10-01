import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { qk } from "../api/keys";
import { redirectToLogin } from "../lib/navigation";
import { RealtimeConnection, socketUrl, type RealtimeEvent, type RealtimeStatus } from "./connection";

const StatusContext = createContext<RealtimeStatus>("closed");

/** Whether the socket is open: while it is not, the queries poll instead. */
export function useRealtimeStatus(): RealtimeStatus {
  return useContext(StatusContext);
}

/** What a doorbell means: the data it points at is stale, so ask for it again. */
export function handleEvent(client: ReturnType<typeof useQueryClient>, event: RealtimeEvent): void {
  if (event.t === "notify") {
    void client.invalidateQueries({ queryKey: qk.notifications });
    void client.invalidateQueries({ queryKey: qk.me });
    // Every workflow step notifies somebody (`services.live_stamp` relies on the same fact), so a
    // doorbell is also the quickest word that a task moved: the lists refresh without waiting
    // for the next heartbeat.
    void client.invalidateQueries({ queryKey: qk.boards });
    // A client's message is not in any room, so it rings as a notification: the chat lists and the
    // open conversation ask again too.
    void client.invalidateQueries({ queryKey: qk.chats });
  } else {
    void client.invalidateQueries({ queryKey: qk.chats });
    void client.invalidateQueries({ queryKey: qk.room(event.id) });
  }
}

export function RealtimeProvider({ pingSeconds = 25, children }: { pingSeconds?: number; children: ReactNode }) {
  const client = useQueryClient();
  const [status, setStatus] = useState<RealtimeStatus>("connecting");

  useEffect(() => {
    const connection = new RealtimeConnection({
      url: socketUrl(),
      pingSeconds,
      onStatus: setStatus,
      // Every (re)connect: whatever rang while we were away was missed.
      onOpen: () => void client.invalidateQueries(),
      onEvent: (event) => handleEvent(client, event),
      onUnauthorized: redirectToLogin,
    });
    connection.start();
    return () => connection.stop();
  }, [client, pingSeconds]);

  return <StatusContext.Provider value={status}>{children}</StatusContext.Provider>;
}
