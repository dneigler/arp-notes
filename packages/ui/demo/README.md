# Demo + axe harness

`npm run demo --workspace packages/ui` serves the harness at http://127.0.0.1:4173.
`npm run test:e2e --workspace packages/ui` visits every scene in four themes (light, dark, system
light, system dark) and runs axe (WCAG 2 A/AA, including `color-contrast`) on each.

## Adding a scene (every C6 bead)

Create `demo/scenes/<area>.js`:

```js
export default {
  id: 'review-desk',            // URL: /#/review-desk
  title: 'Review (desktop)',
  render(container) { /* mount the component into container */ },
}
```

A default export may also be an array of scenes. Scenes are discovered automatically; do not edit
`main.js`. Style demo markup with `--arpn-*` tokens only.
