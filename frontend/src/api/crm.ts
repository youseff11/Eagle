import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

/**
 * The CRM sheets of the real-estate branch (`/api/v1/crm/`, `dashboard/api_crm.py`), nothing to do with the B2B / B2C sheets.
 * The CRM manager makes a sheet for one of the team; the sheet is four columns: the name, the phone, the status and the contact
 * buttons. Who may do what is the server's (`crm.py`): the page draws what the answer says (`can_manage`, `can_contact`).
 */

export type CrmStatus = "" | "interested" | "not_interested" | "quote_requested" | "contacted" | "no_answer";

export interface CrmPerson {
  id: number;
  name: string;
}

export interface CrmStatusChoice {
  value: Exclude<CrmStatus, "">;
  ar: string;
  en: string;
}

export interface CrmSheet {
  id: number;
  title: string;
  assigned_to: CrmPerson | null;
  created_by: CrmPerson | null;
  created_at: string;
  counts: Record<"rows" | Exclude<CrmStatus, "">, number>;
}

export interface CrmRow {
  id: number;
  name: string;
  phone: string;
  status: CrmStatus;
  /** The client code of the chat the WhatsApp button opened, or `""`. */
  chat: string;
}

export interface CrmSheetsResponse {
  ok: true;
  can_manage: boolean;
  holders: CrmPerson[];
  statuses: CrmStatusChoice[];
  sheets: CrmSheet[];
}

export interface CrmSheetResponse {
  ok: true;
  sheet: CrmSheet;
  rows: CrmRow[];
  statuses: CrmStatusChoice[];
  can_manage: boolean;
  can_contact: boolean;
  holders: CrmPerson[];
}

const KEY = ["crm"] as const;

export function useCrmSheets(enabled = true) {
  return useQuery({ queryKey: [...KEY, "sheets"], queryFn: () => api<CrmSheetsResponse>("/api/v1/crm/sheets/"), enabled });
}

export function useCrmSheet(id: number) {
  return useQuery({ queryKey: [...KEY, "sheet", id], queryFn: () => api<CrmSheetResponse>(`/api/v1/crm/sheets/${id}/`), enabled: id > 0 });
}

/** Every write asks the CRM sheets again: a status moves the counts on the list too. */
function useCrmWrite<V, R>(run: (values: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: () => client.invalidateQueries({ queryKey: KEY }) });
}

export function useCreateCrmSheet() {
  return useCrmWrite((values: { title: string; assigned_to: number }) =>
    api<{ ok: boolean; sheet: CrmSheet }>("/api/v1/crm/sheets/new/", { json: values }),
  );
}

export function useSaveCrmSheet(id: number) {
  return useCrmWrite((values: { title?: string; assigned_to?: number }) =>
    api<{ ok: boolean; sheet: CrmSheet }>(`/api/v1/crm/sheets/${id}/save/`, { json: values }),
  );
}

export function useDeleteCrmSheet() {
  return useCrmWrite((id: number) => api<{ ok: boolean }>(`/api/v1/crm/sheets/${id}/delete/`, { json: {} }));
}

export function useAddCrmRows(id: number) {
  return useCrmWrite((rows: { name: string; phone: string }[]) =>
    api<{ ok: boolean; rows: CrmRow[] }>(`/api/v1/crm/sheets/${id}/rows/`, { json: { rows } }),
  );
}

export function useSaveCrmRow() {
  return useCrmWrite(({ id, ...values }: { id: number; status?: CrmStatus; name?: string; phone?: string }) =>
    api<{ ok: boolean; row: CrmRow }>(`/api/v1/crm/rows/${id}/save/`, { json: values }),
  );
}

export function useDeleteCrmRow() {
  return useCrmWrite((id: number) => api<{ ok: boolean }>(`/api/v1/crm/rows/${id}/delete/`, { json: {} }));
}

export function useCrmWhatsapp() {
  return useCrmWrite((id: number) => api<{ ok: boolean; chat: string; row: CrmRow }>(`/api/v1/crm/rows/${id}/whatsapp/`, { json: {} }));
}

/**
 * Pasted or typed lines as rows: one person a line, the name and the number, in either order, split by a tab, a comma or
 * spaces (a pasted spreadsheet gives tabs). The number is the part made of digits, `+`, spaces and dashes.
 */
export function parseCrmLines(text: string): { name: string; phone: string }[] {
  const out: { name: string; phone: string }[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const cells = line.split(/\t|,|؛|;/).map((cell) => cell.trim()).filter(Boolean);
    let name = "";
    let phone = "";
    if (cells.length > 1) {
      for (const cell of cells) {
        if (!phone && /^\+?[\d\s\-()]{6,}$/.test(cell)) phone = cell;
        else if (!name) name = cell;
      }
    } else {
      const found = line.match(/\+?\d[\d\s\-()]{5,}\d/);
      phone = found ? found[0].trim() : "";
      name = (found ? line.replace(found[0], " ") : line).replace(/\s+/g, " ").trim();
    }
    if (name || phone) out.push({ name, phone });
  }
  return out;
}

/** A number for the phone's dialler: digits and a leading `+`. */
export function dialable(phone: string): string {
  const trimmed = phone.trim();
  const digits = trimmed.replace(/[^\d]/g, "");
  return trimmed.startsWith("+") ? `+${digits}` : digits;
}
