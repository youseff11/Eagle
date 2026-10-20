/**
 * A contract won (20/10/2026: «لما حالة تتغير لـ تم التعاقد حط تسقيف واحتفال ... تشجيعًا للموظف»): a write the
 * server answers with `won_now` (it moved the company to «تم التعاقد») calls `celebrate`, and `<Celebration />` in the
 * shell answers with confetti, a «مبروك» card and the cheer. An event on the window, so the writes in `api/b2b.ts` need no component to reach.
 */

export const CELEBRATE_EVENT = "eagle:celebrate";

export interface CelebrateDetail {
  company: string;
}

export function celebrate(company: string): void {
  window.dispatchEvent(new CustomEvent<CelebrateDetail>(CELEBRATE_EVENT, { detail: { company } }));
}
