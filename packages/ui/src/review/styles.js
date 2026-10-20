// ProposalReview styles. Only --arpn-* variables (K§8) and no Tailwind classes, so the component
// themes with the host's token mapping. Shipped as a string and rendered in a <style> element so a
// host needs no extra CSS import (tokens.css is still the host's one stylesheet import).

export const CSS = `
.arpn-rv{position:fixed;inset:0;z-index:1000;font-family:inherit;font-size:14px;line-height:1.5;color:var(--arpn-fg)}
.arpn-rv *,.arpn-rv *::before,.arpn-rv *::after{box-sizing:border-box}
.arpn-rv :focus-visible{outline:2px solid var(--arpn-accent);outline-offset:2px}
.arpn-rv__scrim{position:absolute;inset:0;background:var(--arpn-scrim)}
.arpn-rv__dialog{position:absolute;display:flex;flex-direction:column;overflow:hidden;background:var(--arpn-raised);color:var(--arpn-fg);border:1px solid var(--arpn-border2);box-shadow:var(--arpn-shadow)}
.arpn-rv__dialog:focus{outline:none}
.arpn-rv[data-presentation=dialog] .arpn-rv__dialog{inset:36px 56px;border-radius:20px}
.arpn-rv[data-presentation=formsheet] .arpn-rv__dialog{top:56px;bottom:56px;left:0;right:0;margin:0 auto;width:min(680px,calc(100% - 32px));border-radius:20px}
.arpn-rv[data-presentation=sheet] .arpn-rv__dialog{left:0;right:0;bottom:0;top:44px;border-width:1px 0 0;border-radius:22px 22px 0 0}
.arpn-rv__grab{display:flex;justify-content:center;padding:8px 0 2px}
.arpn-rv__grab span{width:40px;height:5px;border-radius:9px;background:var(--arpn-grab)}

.arpn-rv__head{display:flex;gap:16px;align-items:flex-start;padding:18px 24px 14px;border-bottom:1px solid var(--arpn-border)}
.arpn-rv[data-presentation=formsheet] .arpn-rv__head{padding:16px 20px 12px}
.arpn-rv[data-presentation=sheet] .arpn-rv__head{padding:4px 16px 10px}
.arpn-rv__head-text{flex:1;min-width:0}
.arpn-rv__title{margin:0;font-size:22px;font-weight:700;line-height:1.25}
.arpn-rv[data-presentation=sheet] .arpn-rv__title{font-size:20px}
.arpn-rv__sub{margin:2px 0 0;font-size:14px;color:var(--arpn-muted)}
.arpn-rv[data-presentation=sheet] .arpn-rv__sub{font-size:13px}
.arpn-rv__banner{display:flex;gap:10px;align-items:center;margin:14px 24px 0;padding:10px 14px;border-radius:12px;background:var(--arpn-sel);color:var(--arpn-fg);font-size:14px}
.arpn-rv[data-presentation=formsheet] .arpn-rv__banner{margin:12px 20px 0}
.arpn-rv[data-presentation=sheet] .arpn-rv__banner{margin:10px 16px 0;padding:10px 12px}
.arpn-rv__banner svg{color:var(--arpn-accent)}

.arpn-rv__body{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:14px 24px}
.arpn-rv[data-presentation=formsheet] .arpn-rv__body{padding:0 20px 12px}
.arpn-rv[data-presentation=sheet] .arpn-rv__body{padding:0 16px 12px}
.arpn-rv__cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}
.arpn-rv__col{display:flex;flex-direction:column;gap:16px;min-width:0}
.arpn-rv[data-presentation=formsheet] .arpn-rv__col,.arpn-rv[data-presentation=sheet] .arpn-rv__col{gap:0}

.arpn-rv__sec{display:flex;flex-direction:column;gap:2px}
.arpn-rv__sh{display:flex;align-items:center;gap:8px;margin:0 0 6px}
.arpn-rv[data-presentation=formsheet] .arpn-rv__sh,.arpn-rv[data-presentation=sheet] .arpn-rv__sh{margin:16px 0 4px}
.arpn-rv__sh h3{margin:0;font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--arpn-fg2)}
.arpn-rv__n{font-size:13px;font-weight:600;color:var(--arpn-muted)}
.arpn-rv__grow{flex:1;min-width:0}
.arpn-rv__help{margin:-2px 0 4px;font-size:13px;color:var(--arpn-muted)}

.arpn-rv__row{display:flex;gap:10px;align-items:flex-start;padding:7px 8px;border-radius:10px}
.arpn-rv__row--center{align-items:center}
.arpn-rv[data-presentation=formsheet] .arpn-rv__row,.arpn-rv[data-presentation=sheet] .arpn-rv__row{padding:8px 4px;border-radius:0;border-bottom:1px solid var(--arpn-border)}
.arpn-rv__row input[type=checkbox],.arpn-rv__row input[type=radio]{flex:none;width:20px;height:20px;margin:2px 0 0;accent-color:var(--arpn-accent)}
.arpn-rv[data-presentation=formsheet] .arpn-rv__row input,.arpn-rv[data-presentation=sheet] .arpn-rv__row input{width:22px;height:22px}
.arpn-rv__row--center input{margin:0}
.arpn-rv__line{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.arpn-rv__q{margin-top:2px;font-size:13px;color:var(--arpn-fg2)}
.arpn-rv__strong{font-weight:600}
.arpn-rv__muted{color:var(--arpn-muted)}

.arpn-rv__chip{display:inline-flex;align-items:center;padding:1px 9px;border-radius:999px;border:1px solid var(--arpn-chip-bd);background:var(--arpn-chip-bg);color:var(--arpn-chip-fg);font-size:13px;font-weight:600;line-height:20px;white-space:nowrap}
.arpn-rv__chip--struck{text-decoration:line-through}
.arpn-rv__badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;line-height:16px;white-space:nowrap}
.arpn-rv__badge--high{background:var(--arpn-app-bg);color:var(--arpn-app-fg)}
.arpn-rv__badge--medium{background:var(--arpn-amb-bg);color:var(--arpn-amb-fg)}
.arpn-rv__badge--low{background:var(--arpn-neu-bg);color:var(--arpn-neu-fg)}
.arpn-rv__badge--rejected{background:var(--arpn-del-bg);color:var(--arpn-del-fg)}

.arpn-rv__btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:0 16px;border:1px solid var(--arpn-border2);border-radius:12px;background:transparent;color:var(--arpn-fg);font:inherit;font-size:14px;font-weight:600;cursor:pointer}
.arpn-rv__btn:disabled{opacity:.55;cursor:not-allowed}
.arpn-rv__btn--primary{background:var(--arpn-primary);border-color:var(--arpn-primary);color:var(--arpn-on-primary)}
.arpn-rv__btn--danger{color:var(--arpn-del-fg)}
.arpn-rv__btn--link{min-height:36px;padding:0 8px;border-color:transparent;color:var(--arpn-accent);font-size:13px}
.arpn-rv__btn--more{justify-content:flex-start}
.arpn-rv__ib{display:inline-flex;align-items:center;justify-content:center;flex:none;width:36px;height:36px;padding:0;border:1px solid transparent;border-radius:10px;background:transparent;color:var(--arpn-muted);font:inherit;font-size:13px;font-weight:600;cursor:pointer}
.arpn-rv__ib--close{width:44px;height:44px;color:var(--arpn-fg2)}
.arpn-rv__ib--undo{width:auto;padding:0 8px;color:var(--arpn-accent)}
.arpn-rv[data-presentation=formsheet] .arpn-rv__ib,.arpn-rv[data-presentation=sheet] .arpn-rv__ib{width:44px;height:44px;margin:-8px -6px -8px 0}
.arpn-rv[data-presentation=formsheet] .arpn-rv__ib--undo,.arpn-rv[data-presentation=sheet] .arpn-rv__ib--undo{width:auto;padding:0 8px}
.arpn-rv[data-presentation=formsheet] .arpn-rv__ib--close,.arpn-rv[data-presentation=sheet] .arpn-rv__ib--close{margin:0}
.arpn-rv svg{flex:none;width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.arpn-rv__ib--close svg{width:20px;height:20px}

.arpn-rv__well{padding:10px 12px;border:1px solid var(--arpn-border);border-radius:14px;background:var(--arpn-well)}
.arpn-rv[data-presentation=formsheet] .arpn-rv__well,.arpn-rv[data-presentation=sheet] .arpn-rv__well{padding:8px 12px;margin-bottom:8px}
.arpn-rv__well + .arpn-rv__well{margin-top:8px}
.arpn-rv__lead{margin:0 0 6px;font-size:14px;color:var(--arpn-fg)}
.arpn-rv__well .arpn-rv__row:last-of-type{border-bottom:0}
.arpn-rv__dup{padding:4px 8px 0;font-size:13px;color:var(--arpn-muted)}

.arpn-rv__seg{display:inline-flex;flex:none;overflow:hidden;border:1px solid var(--arpn-border2);border-radius:10px}
.arpn-rv__seg button{min-height:34px;padding:0 10px;border:0;background:transparent;color:var(--arpn-fg2);font:inherit;font-size:13px;font-weight:500;cursor:pointer}
.arpn-rv__seg button[aria-pressed=true]{background:var(--arpn-primary);color:var(--arpn-on-primary);font-weight:700}
.arpn-rv[data-presentation=sheet] .arpn-rv__row--action{flex-wrap:wrap}
.arpn-rv[data-presentation=sheet] .arpn-rv__seg{display:flex;width:100%}
.arpn-rv[data-presentation=sheet] .arpn-rv__seg button{flex:1;min-height:40px;font-size:14px}
.arpn-rv[data-presentation=formsheet] .arpn-rv__seg button{min-height:40px;padding:0 12px;font-size:14px}
.arpn-rv__tog{display:inline-flex;align-items:center;gap:8px;flex:none;font-size:13px;color:var(--arpn-fg2)}
.arpn-rv__host{margin:0;font-size:13px;color:var(--arpn-muted)}
.arpn-rv[data-presentation=formsheet] .arpn-rv__host,.arpn-rv[data-presentation=sheet] .arpn-rv__host{margin-top:14px}

.arpn-rv__foot{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:14px 24px;border-top:1px solid var(--arpn-border);background:var(--arpn-raised)}
.arpn-rv[data-presentation=formsheet] .arpn-rv__foot{padding:12px 20px}
.arpn-rv[data-presentation=sheet] .arpn-rv__foot{flex-direction:column;align-items:stretch;gap:8px;padding:10px 16px 22px}
.arpn-rv__summary{flex:1 1 240px;margin:0;font-size:14px}
.arpn-rv[data-presentation=sheet] .arpn-rv__summary{flex:none;font-size:13px}
.arpn-rv__actions{display:flex;gap:10px}
.arpn-rv[data-presentation=sheet] .arpn-rv__actions{flex-wrap:wrap;gap:8px}
.arpn-rv[data-presentation=sheet] .arpn-rv__btn{min-height:48px;font-size:15px}
.arpn-rv[data-presentation=sheet] .arpn-rv__actions .arpn-rv__btn{flex:1 1 40%}
.arpn-rv[data-presentation=sheet] .arpn-rv__actions .arpn-rv__btn--primary{flex:1 1 100%}
`
