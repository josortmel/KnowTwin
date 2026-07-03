# MISTAKES.md — KnowTwin frontend

## Tarea A — Foundation visual (iter 1/3), 2026-07-02

### 1. Zombie dev server on :3001 served stale pre-token code
- **Qué falló:** al lanzar `vite --port 3001` la verificación inicial mostró
  fondo gris y `getComputedStyle(body)` devolvía vars vacías (`--accent` = "",
  `background-image: none`) pese a que los archivos estaban correctos.
- **Causa real:** había un servidor Vite de una sesión anterior (artefactos
  `.playwright-mcp` con fecha Jun 2) ocupando el puerto 3001. Mi arranque falló
  con `Error: Port 3001 is already in use` (exit 1), así que el navegador seguía
  hablando con el server viejo, que servía el código sin tokens.
- **Cómo se resolvió:** arrancar un server limpio en un puerto libre (:3007) y
  re-verificar. Ahí todos los tokens resolvían y el backdrop ivory se aplicaba.
- **Regla:** cuando la verificación no cuadre con el código, sospecha del server
  antes que del código. Comprueba el exit code del `vite` y usa `--strictPort`
  para que un puerto ocupado falle ruidosamente en vez de saltar a otro puerto.

### 2. El backdrop ivory no se ve pese a estar aplicado en `body`
- **Qué falló:** el backdrop (blobs + grano) está en `body` (index.css), pero la
  pantalla sigue viéndose gris.
- **Causa real:** `src/router.tsx:12` envuelve la app en
  `<div className="min-h-screen bg-gray-50">` y `<nav className="bg-white ...">`.
  Esos elementos viven dentro de `#root` y pintan gris/blanco por encima del
  backdrop del `body`. No es un fallo de la foundation — es el chasis viejo.
- **Cómo se resolvió:** NO se tocó. `router.tsx` es el app-shell, fuera del scope
  de la Tarea A (solo tokens/tailwind/index.css/index.html/main.tsx). Reportado a
  Lienzo como bloqueo del criterio visual; el retrofit del shell es paso (4)/(6)
  del orden de foundation, posterior.
- **Regla:** la foundation de tokens es correcta aunque el shell viejo la tape.
  Verifica la foundation por `getComputedStyle`/vars, no solo por screenshot,
  cuando un wrapper con color sólido puede estar enmascarando el resultado.

## Tarea B — Chasis Electron (iter 1/3), 2026-07-02

### 3. `__dirname is not defined in ES module scope` al arrancar Electron
- **Qué falló:** `npm run build` salía 0, pero `npm run dev` crasheaba en el arranque
  del main con `ReferenceError: __dirname is not defined in ES module scope`.
- **Causa real:** el scaffold Vite de KnowTwin traía `"type": "module"` en package.json.
  Con eso, Node trata `dist-electron/main.js` como ESM, y `__dirname` no existe en ESM.
  El main de EcoDB funciona porque su package.json NO tiene `"type": "module"` → el .js
  se interpreta como CommonJS y `__dirname` está definido.
- **Cómo se resolvió:** quitar `"type": "module"` de package.json (main.js vuelve a
  CJS, `require(...)` + `__dirname` OK). Efecto colateral: `eslint.config.js` era ESM
  (import/export) → renombrado a `eslint.config.mjs` para que siga cargándose como ESM.
  `postcss.config.cjs` ya era CJS. El renderer no se ve afectado (Vite bundlea ESM
  para el navegador con independencia del `type` del package).
- **Regla:** para portar un chasis Electron a un scaffold Vite, revisa `"type"` en
  package.json ANTES de construir. Electron main con `__dirname`/`require` necesita
  CJS; si el proyecto es `type: module`, o quitas el flag (y renombras los configs
  ESM a `.mjs`) o el main debe emitirse como `.cjs`. El build puede salir 0 y aun así
  crashear en runtime — verifica arrancando Electron, no solo compilando.

### 4. `console-message` con firma antigua en Electron 33
- **Qué falló:** `tsc -p tsconfig.electron.json` fallaba: `Property 'message' does not
  exist` en el handler de `webContents.on('console-message', e => e.message)`.
- **Causa real:** ese patrón (`e.message`) es de Electron ≥ ~40. En Electron 33 la
  firma es `(event, level, message, line, sourceId)` — el mensaje es el 3er argumento,
  no una propiedad del event.
- **Cómo se resolvió:** `(_e, _level, message) => console.log('[renderer]', message)`.
- **Regla:** al portar código de una versión de Electron a otra más antigua, las firmas
  de eventos de `webContents` cambian; no asumas la API de la versión origen.

## Tarea #8 — Kit de componentes glass (iter 1/3), 2026-07-02

### 5. Rules-of-Hooks: `useState` tras un `return` condicional
- **Qué falló:** para exponer la galería en /kit sin auth, metí en App.tsx un
  `if (pathname==='/kit') return <KitGallery/>` ANTES del `useState(hasApiKey)`.
  Eso llama un hook condicionalmente (si la ruta es /kit, useState no se ejecuta).
- **Causa real:** viola las Rules of Hooks — el nº de hooks debe ser estable entre
  renders. `npm run build` (tsc+vite) NO lo detecta (eslint no está en el build),
  así que habría pasado silencioso y roto en runtime si la ruta cambiara sin remount.
- **Cómo se resolvió:** mover el `useState` al principio (siempre se ejecuta) y el
  short-circuit de /kit después.
- **Regla:** los early-returns condicionales van SIEMPRE después de todos los hooks.
  El build no protege de esto (eslint sí) — revísalo a mano al añadir returns tempranos.

## Tarea #17 — Dashboard / Command Center (iter 1/3), 2026-07-02

### 1. Mitad de los endpoints del brief daban 500 server-side
- **Qué falló:** el brief listaba /api/v1/stats/knowledge, /stats/system,
  /stats/timeline y /admin/attention-inbox/summary como fuentes; los cuatro
  devuelven 500 (probados con project_id/period, no era param mío).
- **Causa real:** bug de servidor en esos handlers (dominio Hilo). El openapi los
  declara pero el runtime falla. NO es del frontend.
- **Cómo se resolvió:** verificar TODOS los endpoints con curl ANTES de cablear.
  Los vivos (/graph/stats, /twin/coverage, /api/v1/stats/search, /documents,
  /admin/attention-inbox/details) se cablean reales; los caídos se renderizan con
  el estado error/empty del kit (StatCard error, "No activity data available"),
  nunca con placeholder falso. Las queries de los caídos quedan montadas con
  retry:1 para que se enciendan solas cuando Hilo las arregle.
- **Regla:** el openapi dice qué rutas EXISTEN, no qué rutas FUNCIONAN. Curl vivo
  cada endpoint del brief antes de construir. Degradación honesta > dato inventado.

### 2. attention-inbox: summary caído + clases distintas a las del brief
- **Qué falló:** el brief pedía counts vía /summary (500) y clases 'merge
  candidates/disputes/stale docs/pending deletions' que la API rechaza con 400.
- **Causa real:** /details exige query decision_class y solo acepta 4 valores
  EcoDB heredados: low_trust_documents, pending_alias_candidates, stale_memories,
  unconfirmed_relations. summary da 500.
- **Cómo se resolvió:** contar client-side con /details?decision_class=X&limit=1
  leyendo el campo `total` (no hace falta traer items). Labels re-frameados a
  KnowTwin (Lienzo). stale_memories también da 500 → se trata per-row como
  "unavailable" sin tumbar el panel entero.
- **Regla:** cuando un endpoint agregado (summary) está caído, derivar el agregado
  desde el endpoint de detalle si expone `total`. Aislar el fallo por fila, no por panel.

## Tarea #15 — Graph view (iter 1/3), 2026-07-02

### 1. Canvas no lee CSS vars — hay que resolverlas a color concreto
- **Qué falló (previsto):** el brief pide node color = coverage state, cuyos
  colores viven en vars --cov-* (CSS). ForceGraph2D pinta en <canvas>, y
  ctx.fillStyle NO resuelve var(--x): pintaría transparente/negro.
- **Causa real:** el canvas está fuera del árbol CSS; getPropertyValue de una
  custom prop puede devolver la cadena "var(--red)" sin resolver la cadena.
- **Cómo se resolvió:** helper resolveColor(expr) que crea un <span> temporal,
  le pone style.color = expr, lo mete en el DOM, lee getComputedStyle().color
  (rgb ya resuelto) y lo quita. Se memoiza el mapa de estados una vez.
- **Regla:** para pasar colores del design system a un canvas, resuélvelos vía
  getComputedStyle de un elemento real, no leas la custom prop directamente.

### 2. react-force-graph-2d infla el bundle 200kB → code-split
- **Qué falló:** tras `npm i react-force-graph-2d` el bundle pasó de 308kB a
  503kB (warning de Vite >500kB). Esa dep solo se usa en /graph.
- **Cómo se resolvió:** lazy(() => import('./pages/GraphPage')) + <Suspense> en el
  router. El grafo queda en un chunk aparte (194kB) que solo carga al abrir /graph;
  el index vuelve a 310kB.
- **Regla:** deps pesadas de una sola ruta van SIEMPRE detrás de React.lazy. No
  hagas pagar el arranque de toda la app por una vista que quizá no se visita.

### 3. El grafo del demo tiene 60 entidades y 0 triples → sin edges
- **Qué falló:** /graph/all devuelve edges:[] (edge_count 0) y /graph/neighbors
  vacío. El force-graph renderiza un "node cloud" sin conexiones.
- **Causa real:** estado real del demo (aún no hay relaciones extraídas), no un bug.
- **Cómo se resolvió:** asumido y documentado. El valor de iter 1 está en el
  inspection panel (claims por entity vía /claims?subject_entity=). Hop slider y
  cluster legend quedan diferidos (serían controles inertes con 0 edges/clusters);
  en su lugar, leyenda de coverage (siempre útil, explica el color del nodo).
- **Regla:** no metas controles que no hacen nada con los datos actuales (afordancia
  inerte, mismo problema a11y que un botón-stub). Sustitúyelos por algo que sí
  informe, y difiere lo inerte con una nota al arquitecto.

## Dashboard upgrade post-Hilo-fix, 2026-07-02

### 1. HMR mostró 2 errores falsos al renombrar un export en pleno guardado
- **Qué pasó:** al cambiar useDashboard.ts (quitar useAttentionClass, añadir
  useAttentionSummary) la consola del navegador escupió "does not provide an export
  named 'useAttentionClass'". Parecía un bug.
- **Causa real:** artefacto de HMR: Vite recargó useDashboard.ts (ya sin el export)
  antes de recargar el index.tsx que aún lo importaba. Transitorio del editado en
  caliente, NO del código final. El build (tsc) salió exit 0 y un reload limpio dio
  0 errores.
- **Regla:** ante un error de "export named X" en HMR justo tras editar, recarga
  fresco y comprueba el build antes de creerlo. Es ruido del hot-reload, no un fallo.

### 2. summary usa 'stale_claims', details usaba 'stale_memories'
- **Qué pasó:** al cablear el count server-side, la clave en /summary es
  `stale_claims`, pero /details (antes) aceptaba `stale_memories`. Nombres distintos
  para lo mismo entre endpoints.
- **Cómo se resolvió:** usar las claves EXACTAS que devuelve /summary.classes como
  fuente de verdad para el mapa de clases. summary trae las 6 claves de una.
- **Regla:** no asumas que dos endpoints nombran igual la misma entidad. Lee las
  claves reales del que vas a consumir.

## T17 Command Center rewrite (EcoDB port + curator correction), 2026-07-02

### 1. Contrato ambiguo entre brief y fuente EcoDB → leí el código del backend
- **Qué pasó:** el brief listaba /api/v1/stats/knowledge con `merged_entity_count`
  pero la nota de port decía "orphan_entity_count use as-is". openapi.json devuelve
  schemas genéricos (`additionalProperties:true`), inútil para nombres de campo.
- **Causa real:** el endpoint es Super-only y no tengo la API key (perdida tras
  compactación), así que no pude curl en vivo.
- **Cómo se resolvió:** leí `api/stats.py:401` directo. Devuelve AMBOS campos
  (`merged_entity_count` Y `orphan_entity_count`), `_claim_count` no `_memory_count`,
  y `duplicate_candidate_count` SOLO sin project_id. Cablée la llamada system-wide.
- **Regla:** cuando openapi da schemas opacos y no hay key, el código del backend es
  el contrato definitivo — más fiable que curl. Léelo.

### 2. refetchOnWindowFocus no actualiza queries ya cacheadas de forma fiable
- **Qué pasó:** parcheé el mock bridge en caliente (disputes 2→16, etc.) y disparé
  `window.dispatchEvent(new Event("focus"))`. Documents actualizó (tiene
  refetchInterval/polling) pero Claims/Disputes/Inbox/InterviewProgress se quedaron
  con la fixture vieja; InterviewProgress mostró error (cacheó el 404 inicial).
- **Causa real:** el focus refetch solo re-fetchea queries stale; las que ya tenían
  data fresca (o error con retry:false) no se re-dispararon.
- **Cómo se resolvió:** forcé remount navegando SPA (Setup→Dashboard). El remount
  re-fetchea todo con el mock parcheado. Sin full reload → el mock persiste.
- **Regla:** para revalidar el dashboard entero contra fixtures nuevas, remonta vía
  nav SPA; no confíes en el focus event.

### 3. Interview Progress: /projects/{id}/scores no trae nombre de empleado
- **Qué pasó:** Lienzo pidió mostrar "Juan García: 16.83". El endpoint
  (`api/scoring.py:150`, curator-only) devuelve `[{employee_id, score, components,
  claim_count}]` — sin nombre.
- **Cómo se resolvió:** resolví el nombre con /projects/{id}/members
  (useProjectMembers), fallback `Employee #{id}`. Score con framing de proceso
  (§7.6), nunca ranking de personas.
- **Regla:** si un endpoint devuelve solo IDs y el diseño pide nombres, cruza con el
  endpoint de members; no asumas que el nombre viaja en el payload de scores.

## T19 Ingestion vista dedicada (port EcoDB), 2026-07-02

### 1. DocumentListItem NO trae los campos que el detail sí
- **Qué pasó:** iba a tipar la lista con visibility/trust_hint/retry_count, pero
  `api/documents.py:61` (DocumentListItem) solo tiene id/uri/filename/doc_type/
  workspace_id/project_id/status/created_at. Esos campos extra viven solo en
  DocumentResponse (GET /documents/{id}).
- **Cómo se resolvió:** dos tipos separados — Document (lista, polling) y
  DocumentDetail (detail endpoint). El DocDetailPanel usa useDocumentDetail(id),
  no reusa la fila de la lista.
- **Regla:** list-item y detail de un mismo recurso suelen tener shapes distintos.
  No asumas que la fila trae todo; lee ambos modelos del backend.

### 2. Colisión de hue: Ingestion nav teal = Graph teal
- **Qué pasó:** Lienzo pidió Ingestion nav en teal #4FA0A0, pero ese es exactamente
  --sec-graph (ya usado por Graph). KnowTwin no tiene token --sec-ingestion (EcoDB
  sí). Dos items de nav en el mismo teal rompen la lógica de "legend por color".
- **Cómo se resolvió:** usé var(--sec-graph) (valor exacto pedido) SIN inventar
  token nuevo, y lo marqué en el BUILDER_REPORT para que Lienzo decida si quiere un
  --sec-ingestion distinto. Regla dura: no cambio el design system sin su OK.
- **Regla:** si una instrucción de color choca con un token existente, sigue el
  valor literal pero no inventes tokens — reporta la colisión al arquitecto.

### 3. Upload EcoDB abre picker en MAIN; KnowTwin lee File en el RENDERER
- **Qué pasó:** EcoDB "Add document" llama window.ecodb.openFile (picker en main).
  KnowTwin uploadDocument espera {filename, bytes} — el File se lee en el renderer.
- **Cómo se resolvió:** input file oculto disparado por el botón "Add document" +
  selector de trust_hint; onChange lee el File y llama useUploadDocument. El bridge
  ya valida tamaño (100MB, defense-in-depth VS4).
- **Regla:** al portar UX de upload entre EcoDB y KnowTwin, revisa DÓNDE se lee el
  archivo (main vs renderer) — el contrato del bridge difiere.

## T15 Graph Studio rewrite (port EcoDB GraphStudio), 2026-07-02

### 1. nodeLabel tooltip (VS-G1) eliminado portando fielmente EcoDB
- **Qué pasó:** mi Graph anterior usaba nodeLabel={escapeHtml(name)} (tooltip via
  innerHTML de float-tooltip) — el sink de VS-G1. Lo había mitigado con escape.
- **Descubrimiento al portar:** EcoDB GraphStudio NO usa nodeLabel en absoluto —
  dibuja las labels en el canvas (drawNode) al hacer zoom. No hay tooltip, no hay
  sink.
- **Cómo se resolvió:** eliminé nodeLabel por completo (paridad con EcoDB). Labels
  en canvas via drawNode > labelZoom. VS-G1 desaparece de raíz, no se mitiga.
- **Regla:** antes de mitigar un sink, comprueba si la referencia que portas siquiera
  lo usa. A veces la fuente ya lo evitó y el fix correcto es quitarlo, no escaparlo.

### 2. Canvas colors no pueden leer CSS vars → resolver a rgb() y convertir glow
- **Qué pasó:** drawNode necesita el color del nodo (coverage state) pero el canvas
  no lee var(--cov-*). Además el glow usa hexToRgba, que asume hex.
- **Cómo se resolvió:** la vista resuelve cada color coverage a rgb() (span temporal
  + getComputedStyle) una vez y lo mete en node.color. Añadí toRgba() en graphTypes
  que acepta rgb()/rgba() Y hex (getComputedStyle devuelve rgb(), no hex) para el
  radial-gradient del glow.
- **Regla:** getComputedStyle devuelve rgb()/rgba(), nunca hex. Cualquier helper de
  alpha en canvas debe parsear ambos formatos.

### 3. merge-entities body: source_node_id/target_node_id (NO winner/loser)
- **Qué pasó:** el spec T16 decía {winner_id, loser_id}. El código real
  (api/admin.py:1031) usa {source_node_id, target_node_id, keep_as_alias}. IDs =
  GRAPH NODE IDs (de /graph/all nodes[].id).
- **Cómo se resolvió:** hook useMergeEntities con el body real; en doMerge convierto
  node.id a Number. Verificado contra el backend, no contra el spec.
- **Regla:** el spec puede tener nombres viejos. El código del endpoint manda.

## T20 Claims Explorer (port EcoDB KnowledgeExplorer), 2026-07-02

### 1. /claims server params ≠ lo que decía el brief
- **Qué pasó:** el brief/spec decían que source_type es filtro server-side de /claims.
  El código real (api/claims.py:362) solo acepta: project_id, subject_entity,
  predicate, corroboration_level, dispute_state, limit, offset. NO source_type, NO
  sensitivity, NO tags.
- **Cómo se resolvió:** server-side = corroboration_level/dispute_state/subject_entity/
  limit. source_type y sensitivity → filtro CLIENTE (el Claim trae ambos campos).
  tags → NO tiene path (ni server param ni campo en Claim) → dropeé el filtro de tags
  y lo marqué a Lienzo.
- **Regla:** verifica los Query params del endpoint en el código antes de asumir que
  un filtro es server-side. El brief puede prometer filtros que el backend no expone.

### 2. Chips dinámicos por valores presentes, no por enum adivinado
- **Qué pasó:** §7.4 lista sensitivity como public/team/restricted; el brief decía
  public/restricted/confidential. Valores reales del seed inciertos.
- **Cómo se resolvió:** source_type y sensitivity chips se generan de los valores
  ÚNICOS presentes en los claims cargados (new Set(...)). Cero adivinación: si el
  seed usa "team", aparece "team".
- **Regla:** para filtros cliente sobre un enum incierto, deriva las opciones de los
  datos reales, no de una lista hardcodeada que puede no coincidir.

### 3. /twin/query es POST pero lo quiero cacheado → useQuery con post en queryFn
- **Qué pasó:** useTwinQuery existente es useMutation. Para search-as-you-type con
  debounce quería caché + isPending por query.
- **Cómo se resolvió:** añadí useTwinSearch = useQuery cuyo queryFn hace post(), key
  por [project, question], enabled con question no vacío. El input debouncea 300ms.
- **Regla:** que un endpoint sea POST no obliga a useMutation. Si el POST es
  idempotente-de-lectura (search), useQuery con post en queryFn da caché gratis.

## T21 Decisions Inbox (port EcoDB DecisionsInbox), 2026-07-02

### 1. Una sola fuente para las 6 clases: /admin/attention-inbox/details
- **Qué pasó:** EcoDB usaba un endpoint rico aparte para alias (useAliasCandidates)
  y el genérico details para el resto. En KnowTwin, /admin/attention-inbox/details
  (api/admin.py:248, super/ceo) devuelve items para las 6 clases incl. alias
  (con source_name/target_node_name/confidence/occurrences).
- **Cómo se resolvió:** un solo useInboxDetails(decisionClass) para las 6. El item
  es permisivo (InboxItem con todos los campos opcionales) y cada detail component
  lee los suyos. Menos hooks, menos superficie.
- **Regla:** si un endpoint genérico ya devuelve el shape por clase, no metas un
  segundo endpoint específico "porque EcoDB lo hacía".

### 2. Los ids de acción difieren por clase — no todos son claim_id
- **disputes:** item.id = claim id → PUT /claims/{id}/resolve.
- **deletions:** item.id = REQUEST id → PUT /claims/deletion-requests/{id}/review
  (NO el claim_id, que viene aparte en item.claim_id).
- **stale:** item.id = memory/claim id → PUT /memories/{id}/staleness.
- **alias:** item.id = alias candidate id → PUT /admin/alias-candidates/{id}.
- **Regla:** en un inbox multi-clase, cada acción mapea item.id a un recurso
  distinto. Verifica qué id espera cada endpoint antes de cablear.

### 3. GDPR wording obligatorio (§4) + acciones compliant §1.3
- Deletion approve = 2-step con el texto EXACTO de DESIGN §4: "This permanently
  deletes the claim and cannot be undone." No improvisar la copia.
- Reusé el componente Button (variant primary/default/danger) en vez del ActionBtn
  custom de EcoDB (que usaba text-red / color:ACCENT → §1.3 fail). Tabs activos y
  WhyBox: texto ink, color solo en dot/border/tint. Cero texto coloreado pequeño.

## T16 Ontology Console rewrite (port EcoDB 1115L), 2026-07-02

### 1. searchNodes imperativo (no hook) para el merge flow
- **Qué pasó:** el merge flow necesita buscar nodos DENTRO de callbacks async
  (startMerge auto-carga similares; doMerge re-resuelve el source por nombre). Un
  hook useQuery no sirve ahí (no se llama en callbacks).
- **Cómo se resolvió:** helper `searchNodes(q, limit)` que llama get('/graph/search')
  directo. useGraphSearch (hook) se queda para la búsqueda declarativa del Graph.
- **Regla:** para búsquedas dentro de flujos async imperativos, un helper con get()
  directo; los hooks useQuery son para lectura declarativa en render.

### 2. Merge source resuelto por nombre EXACTO, nunca fuzzy (VS-ONT-H1)
- **Qué pasó:** merge-entities necesita el GRAPH NODE ID del source. La lista de
  vocabulary da name+type, no id. Hay que resolver el id vía /graph/search.
- **Cómo se resolvió:** en doMerge, buscar y exigir EXACTAMENTE 1 match con nombre
  idéntico (case-insensitive). 0 o >1 → abortar. Un near-name o un nodo renombrado
  mergearía el nodo equivocado.
- **Regla:** cuando resuelves un id por búsqueda para una op destructiva, exige match
  exacto único. Nunca caigas a un resultado fuzzy "el más parecido".

### 3. /admin/alias-candidates acepta status + review soporta reverse
- **Qué pasó:** el shape real (api/admin.py:800 AliasCandidateRow) = {id, source_name,
  target_node_id, target_node_name, confidence, occurrences, status,...}. GET acepta
  ?status=pending|approved|rejected|archived. El review (PUT) acepta {status, merge,
  reverse}: reverse=true mergea target INTO source (invierte el superviviente).
- **Cómo se resolvió:** tabs de status + control ⇄ invert que fija reverse antes de
  confirmar el merge. Verificado en el código, no adivinado.
- **Regla:** lee el body model del endpoint (Literal/Field) — campos como `reverse`
  cambian la semántica de una op destructiva y no siempre están en el brief.

## T22 Shell Upgrade (port EcoDB shell), 2026-07-02 — LAST TASK

### 1. ErrorBoundary reset-on-navigation = React key, no lógica extra
- **Qué pasó:** Lienzo pidió ErrorBoundary "keyed by route so crashes reset on
  navigation". El ErrorBoundary (clase) guarda error en state; no se resetea solo.
- **Cómo se resolvió:** `<ErrorBoundary key={location.pathname}>` en AppShell. Al
  cambiar la ruta, React remonta el boundary (key nueva) → state limpio. Sin código
  de reset manual.
- **Regla:** para resetear estado de un componente al cambiar contexto, cambia su
  `key`. React remonta y limpia. Vale para ErrorBoundary, forms, cualquier state.

### 2. ⌘K palette: navegación cross-view vía URL param, no store global
- **Qué pasó:** EcoDB CommandPalette usaba Zustand stores (viewStore.setView,
  seedExplorer) para saltar entre vistas con estado sembrado. KnowTwin usa
  react-router.
- **Cómo se resolvió:** el palette hace navigate(`/graph?center=<name>`) y el Graph
  lee ?center= con useSearchParams (effect que setCenter+setFull(false) cuando el
  param cambia). Cero store global; la URL ES el estado compartido.
- **Regla:** en apps con router, el deep-link por query param sustituye al store
  global para pasar estado entre vistas. Más simple y bookmarkeable.

### 3. SystemMonitor sin agent presence (stripped) — solo lo que el endpoint da
- EcoDB mostraba presence de agentes vía SSE store. KnowTwin no tiene SSE presence.
- Monitor solo muestra db counts (claims/nodes/triples) + embeddings.status de
  /api/v1/stats/system. No inventé un endpoint de presence que no existe.
- **Regla:** al portar un widget, quita lo que dependa de infraestructura que el
  target no tiene (SSE presence). No lo fakees.

## Bug hunt (post-rebuild), 2026-07-02

### 1. BUG (mío): botones "Add" de Predicates/Dictionary no hacían submit
- **Qué pasó:** `<Button variant="primary" onClick={() => {}}>Add</Button>` dentro de
  un `<form onSubmit>`. El componente Button hardcodea type="button" → un click NO
  dispara el submit del form. onClick vacío → click no hacía NADA. Solo Enter en un
  input enviaba el form.
- **Causa real:** al portar de EcoDB (que usaba `<button type="submit">` crudo) metí
  el Button del kit sin pasar type. Button es type="button" por defecto.
- **Cómo se resolvió:** `type="submit"` en esos 2 botones (Button hace spread de
  {...rest} DESPUÉS de type="button", así que type="submit" lo sobreescribe).
  Verificado: requestSubmit ahora dispara POST /admin/predicates.
- **Regla:** un Button del kit dentro de un form NO envía el form al click (es
  type=button). Para el submit-por-click, pásale type="submit" explícito.

### 2. Invalidaciones cross-view (INV-1..5, encontradas con Lienzo)
- Las mutations invalidaban su propia query pero no las de OTRAS vistas que muestran
  el mismo dato. Añadido en onSuccess:
  - useResolveDispute → +inbox-details +attention-summary
  - useAssignResolver → +inbox-details
  - useUpdateStaleness → +claims +knowledge-stats
  - useReviewDeletion → +inbox-details +attention-summary
  - usePromoteClaim → +graph-totals +knowledge-stats (promote crea triples)
- **Regla:** al invalidar tras una mutation, piensa en TODAS las vistas que muestran
  ese dato, no solo la vista actual. Un claim aparece en Explorer, Dashboard, Graph,
  Decisions — invalida todas sus keys.

### 3. Verificado OK (no eran bugs)
- Alias approve refresh: la invalidación de useReviewAlias SÍ refresca (verificado en
  browser — el candidato aprobado desaparece de la lista pending). El bug de EcoDB no
  se reprodujo en KnowTwin.
- Scroll overflow: todos los contenedores de lista tienen overflow-y-auto + min-h-0.
- Error states: merge/delete/resolve fallidos → toast o InlineWarn, sin romper el flujo.

### 4. FINDING abierto (decisión de producto): claim count system-wide vs project
- Dashboard card "Claims" usa /api/v1/stats/system.db.claims_count (SYSTEM-WIDE, 34),
  pero todo lo demás del dashboard es project-scoped (project_id=1) y Explorer usa
  /claims?project_id=1 (17). Inconsistencia visible. Pendiente decisión de Pepe/Lienzo
  sobre qué count mostrar (no lo cambio unilateralmente — es semántico).

## Sesión bug-fixes (Pepe test session) + UPDATE #27, 2026-07-03

### 1. FIX-30 Graph hover — verificación con canvas (sin bug de código)
- **Reto:** react-force-graph pinta en canvas; hover se verifica con ratón REAL.
- eventos MouseEvent sintéticos dispatchados NO disparan el hover de react-force-graph
  (usa su propio tracking de puntero). Solución: `page.mouse.move` (Playwright real) +
  localizar el nodo escaneando píxeles del canvas por color (centroide por celda, no
  centroide global — global cae entre nodos del mismo color y falla el hit-test).
- Implementación: onNodeHover→hoveredId, adjacency Map desde data.links (useMemo),
  drawNode dim alpha 0.15 a no-vecinos + label forzado a vecinos + ring extra al hovered,
  linkColor atenúa aristas no incidentes.

### 2. UPDATE #27 — el brief relay chocaba con el backend real (4 deltas)
- **Regla reforzada:** verificar SIEMPRE contra el source Python del backend antes de
  implementar un brief, aunque venga "confirmado por Hilo". El brief decía `name`,
  `api_key_hint`, `base_url`, `provider_id` — el backend (api/providers.py,
  api/cell_configs.py con extra="forbid") usa `provider`, `api_key_masked`, SIN base_url
  (lo rechaza 422), y cells usan `provider` (nombre) + `agent_identifier` REQUERIDO.
  Reporté los deltas a Lienzo antes de codificar; Hilo confirmó agent_identifier="default".
- /providers/{name}/models devuelve `{provider, models}`, no `string[]` pelado — unwrap .models.

### 3. Falso bug: refresh in-place no funcionaba con mock SÍNCRONO
- **Síntoma:** tras POST provider, el listado no refrescaba (rows=0) pese a que el
  refetch GET SÍ se disparaba y el cache de React Query tenía data=2, observers=1, success.
- **Causa real:** el mock de test resolvía `Promise.resolve(...)` en el MISMO microtask.
  Eso confunde el batching/notify de React Query en dev+StrictMode → el observer no
  re-renderiza. NO es bug de código.
- **Prueba:** con mock async (`setTimeout 40ms`, latencia tipo IPC real) el refresh
  funciona perfecto (rows [1,1,1,1,1]). El bridge Electron real es async → correcto.
- **Regla:** los mocks del bridge deben tener latencia (setTimeout) para reproducir el
  comportamiento real de React Query. Un mock síncrono da falsos negativos de refresh.
- **Diagnóstico útil:** inspeccionar el cache de React Query vía fiber walk desde #root
  (`memoizedProps.client.getQueryCache().getAll()`) para ver status/data/observers reales.

### 4. Interview `message` (LLM) no se renderizaba
- /respond devuelve `message` (pregunta LLM del entrevistador) pero RespondResult no lo
  tipaba y InterviewView solo mostraba "Extracted N claims". Añadido `message?` al tipo +
  handleSendText/handleSendVoice usan `result.message` como texto del system message
  (fallback al status line). Twin `answer` en Explorer YA se renderizaba (TwinAnswer+SafeText).

## TASK #29 — Twin UX redesign (conversación), 2026-07-03

### 1. DELTA de contrato: /twin/query NO acepta empleado
- El brief pedía "selected employee determines the context for twin queries" pero el
  backend TwinQuery (api/twin.py:31) solo acepta `{question, project_id}` — SIN param de
  empleado. El selector de empleado es FRAMING/contexto presentacional (§7.6), NO filtra
  server-side. Implementado como framing per spec explícito de Lienzo (body {question,
  project_id:1}); anotado a Lienzo para que nadie asuma que filtra.
- Al cambiar de empleado se resetea el hilo de conversación (contexto nuevo).

### 2. Archivos huérfanos tras replace
- TwinView reescrito entero → TwinChat.tsx, SourcePanel.tsx, DisputePanel.tsx quedan
  sin usar (solo los referenciaba el TwinView viejo). tsc NO los marca (unused files no
  dan error). NO los borré (regla: no borrar código no relacionado sin permiso) — flagged
  a Lienzo para que decida. CoverageOverview SÍ se reusa.

### 3. #27 C1 — mi propia violación §1.3
- El texto de validación de slug usaba `style={{color:"var(--red)"}}` — texto de color
  a <18px falla contraste WCAG (§1.3). Corregido a `text-ink-3` + borde rojo en el input
  (inset box-shadow var(--red)) como señal, mismo patrón que NoteInput de #31. Regla: el
  ESTADO va en borde/tint/dot, nunca en el color del texto pequeño.

## Batch 5 tasks (#32/#35/#34/#33/#36), 2026-07-03

### 1. BUILD ROJO por edición no-atómica (mi peor error del batch)
- Al añadir #33 templates edité los IMPORTS primero (antes de escribir los
  consumidores). Estado intermedio: imports "unused" → un linter los auto-removió Y
  un build ajeno (Lienzo/adversarial) corrió tsc en ese instante → exit 2. Luego el
  linter dejó los consumidores referenciando símbolos no importados → segundo roto.
- FIX definitivo: cambios multi-ubicación (imports + componentes + uso) = UN SOLO
  Write del archivo completo. Build verde ANTES de reportar. Nunca dejar código
  parcial en disco.
- REGLA (Lienzo): el build debe estar VERDE EN TODO MOMENTO. Otros agentes corren tsc
  continuamente; una ventana roja de segundos los rompe.

### 2. HMR stale de Vite tras el build roto
- Tras arreglar el archivo, el dev server seguía lanzando "TemplatesSection is not
  defined" en runtime AUNQUE tsc pasaba. Era un módulo HMR cacheado del estado roto.
  Fix: navigate full-reload (no basta con cambiar de tab). Lección: si tsc pasa pero el
  browser da ReferenceError de algo que SÍ existe, es HMR stale → reload duro.

### 3. Deltas de contrato (verificar SIEMPRE el source Python)
- #34 suggested-topics: devuelve {project_id, topics:[{entity_name,...}]} — entity_name
  (no `entity`), envuelto en {topics}.
- #36 History: /claims dispute_state es filtro de valor ÚNICO → 2 queries (favor+against)
  merge. Y ClaimResponse NO expone resolution_note/resolved_by/resolved_at (solo
  dispute_state+updated_at). No inventé campos; flageé a Lienzo/Hilo.
- #32: con force=true el backend SALTA niveles (no adjacente), único constraint
  interview+validated→409. nextLevel por cap de fuente evita el 409.

### 4. Refresh de mutación: mock SÍNCRONO da falso negativo (repetido)
- El refresh in-place tras add/delete/reverse SOLO funciona con mock async (setTimeout).
  Mock síncrono (Promise.resolve mismo microtask) rompe el notify de React Query en
  dev+StrictMode. Todos los tests del batch usaron latencia ~40ms → refresh correcto.

## #37 + #38 (Agent Config v2 + Processes/HR), 2026-07-03

### 1. Relay de contratos ADELANTADO al source real (verificar siempre el .py)
- Lienzo relayó "next-steps → [{action, priority, gaps?}]" pero el source (api/projects.py:471)
  devuelve {steps:[{action, label}]} — sin priority/gaps (los gaps van en el label string).
  Hilo SÍ había pusheado OTRAS cosas (status +open_disputes, OffboardingCreate +department/
  exit_date/disposition, ProjectResponse +employee_name) → el relay mezclaba lo real con lo
  aspiracional. Regla: cada delta de contrato se verifica en el source ANTES de codificar,
  aunque el relay diga "confirmado por Hilo".

### 2. Campos de formulario que NO persisten
- El wizard #38 pide reporting_manager/replacement_name/priority pero OffboardingCreate no
  los tiene. Como el modelo NO es extra=forbid, pydantic los IGNORA silenciosamente (no 422).
  Los envío igual (no rompe) pero flageé a Lienzo que no se guardan hasta que Hilo añada
  columnas. No colecciono datos que desaparecen sin avisar.

### 3. Vocab rename HR: hacerlo en los BADGES centrales, no string a string
- El rename user-facing (Claims→Knowledge items, Disputed→Contradiction, etc.) se hace UNA
  vez en los 3 badges (CorroborationBadge/DisputeBadge/CoverageStateBadge) y se propaga a
  TODAS las vistas. Los códigos (single_source, disputed…) siguen igual en el wire — solo
  cambia el label. Mucho más eficiente que editar cada heading. El sweep profundo de headings/
  tooltips individuales queda como pasada dedicada si se pide.

### 4. #37 reset: el config trae prompt_template_id
- El CellConfig del backend incluye prompt_template_id → asociación directa card↔template
  (mejor que matchear por cell_type). POST /cells/configs/{id}/reset resetea config + prompt.
  El card remonta via key con updated_at para reflejar el reset (refresh in-place depende del
  refetch, mismo timing React Query ya conocido; con backend async real refresca).
