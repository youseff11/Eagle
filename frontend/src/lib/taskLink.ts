/**
 * Where the classic new-task form opens from a client's messages and the files ticked in them (`views.ops_task_new`
 * reads `messages=` and `files=`, each one id or a comma-joined list, and checks every id against the messages and
 * the client again: this link only has to be convenient). The form is the operation screen's, which is not ported yet.
 */
export function newTaskUrl(messages: number[], files: number[]): string {
  const parts = [`messages=${messages.join(",")}`];
  if (files.length > 0) parts.push(`files=${files.join(",")}`);
  return `/ops/tasks/new/?${parts.join("&")}`;
}
