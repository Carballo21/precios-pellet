# Monitor de precios del pellet · España

Cada dos días la app lee los precios en **36 puntos de venta** (grandes superficies, distribuidores y venta directa de fábrica). Después:

1. pasa todos los precios a unidades comparables (€/t y €/saco de 15 kg, con y sin IVA);
2. separa el precio en **origen** (fábrica) y en **destino** (consumidor);
3. los compara con los índices de **AVEBIOM**: el trimestral a consumidor y el mensual EXW en fábrica;
4. te avisa por **Telegram, email o GitHub** cuando se cumple alguna de tus alarmas;
5. publica un **panel web** con la evolución, la tabla de precios y las alertas.

Todo funciona con servicios gratuitos: GitHub Actions ejecuta el programa, GitHub Pages publica el panel y Telegram envía los avisos. No necesitas servidor ni tarjeta.

---

## Puesta en marcha (unos 15 minutos, una sola vez)

### 1. Crea el repositorio en GitHub
1. Crea una cuenta en <https://github.com> si no tienes.
2. Pulsa **New repository**, ponle un nombre (por ejemplo, `precios-pellet`) y márcalo como **Public**. Pages es gratis en repositorios públicos y Actions no tiene límite de minutos. Los datos son precios públicos y tus claves quedan cifradas en *Secrets*.
3. Pulsa **uploading an existing file**, arrastra **todo el contenido** de esta carpeta (incluida la carpeta oculta `.github`) y pulsa **Commit changes**.
   - Si tu sistema oculta `.github`, crea el archivo a mano con **Add file → Create new file**, nombre `.github/workflows/precios.yml`, y pega el contenido.

### 2. Activa el panel web
**Settings → Pages → Build and deployment → Source: Deploy from a branch**, rama `main` y carpeta `/docs` → **Save**.
En un par de minutos el panel estará en `https://TU-USUARIO.github.io/precios-pellet/`.

### 3. Crea el bot de Telegram para las alarmas
1. En Telegram, abre **@BotFather**, envía `/newbot` y sigue los pasos. Te dará un **token** (`123456:ABC...`).
2. Escribe cualquier cosa a tu bot nuevo.
3. Abre en el navegador `https://api.telegram.org/botTU_TOKEN/getUpdates` y copia el número de `"chat":{"id": ...}`. Ese es tu **chat id**.
4. En GitHub ve a **Settings → Secrets and variables → Actions → New repository secret** y crea:
   - `TELEGRAM_BOT_TOKEN` con el token
   - `TELEGRAM_CHAT_ID` con el chat id

> **Sin Telegram:** las alarmas también se abren como *issue* en tu repositorio, y GitHub te las manda por email automáticamente. Para recibirlas directamente por email (por ejemplo, desde Gmail con una *contraseña de aplicación*), crea los secrets `SMTP_HOST` (`smtp.gmail.com`), `SMTP_PORT` (`587`), `SMTP_USER`, `SMTP_PASS` y `EMAIL_TO`, y pon `email: true` en `config/alertas.yaml`.

### 4. Primera ronda
**Actions → Ronda de precios del pellet → Run workflow**. Tarda entre 5 y 10 minutos. Después se ejecuta sola cada dos días a las 06:17 UTC.

### 5. Revisa la primera ronda (importante)
Abre el panel y mira la columna **Estado**:
- **✕ Error**: la web ha bloqueado al robot o ha cambiado. Pasa el ratón para ver el motivo (ver *Arreglar una fuente*).
- **! Anómalo**: el precio en €/t sale fuera de lo razonable. Casi siempre es un `kg` mal puesto (un palet configurado como saco, por ejemplo).
- Revisa a mano las fuentes marcadas `verificar: true` en `config/fuentes.yaml`: son las que tienen dudas de formato, kg o IVA.

---

## Cómo se separa origen y destino

| | Qué es | Con qué se compara |
|---|---|---|
| **Destino** | Precio de venta al consumidor en tiendas y distribuidores (saco, palet, granel) | Índice de precios de la biomasa (IPB) de AVEBIOM: trimestral, IVA incluido, transporte medio de 200 km en granel |
| **Origen** | Precio de venta directa de fábrica (fabricantes con tienda online) y presupuestos que añadas tú | Índice EXW de AVEBIOM: mensual, en fábrica, sin IVA, camión completo de ENplus A1 |

El panel muestra también el **diferencial destino − origen**: la media de destino sin IVA menos el precio en fábrica. Es el margen que se llevan la distribución, el transporte y el ensacado.

**Una advertencia sincera sobre el origen:** casi ningún fabricante publica su precio de fábrica. Las tres fuentes de origen son ventas directas de fabricantes, que suelen incluir transporte, y sirven solo como aproximación. Para afinar, apunta los presupuestos que pidas a fábricas en `data/presupuestos_origen.csv` (fecha, fabricante, región, formato, €/t sin IVA y condiciones). Aparecerán en el gráfico de origen.

## Mantener al día los índices de AVEBIOM
AVEBIOM publica el IPB cada trimestre (enero, abril, julio y octubre) y el EXW cada mes, en PDF. La app vigila su página y **te avisa cuando sale uno nuevo**. Entonces añade una línea a:
- `data/avebiom_ipb.csv`: trimestre, fecha de inicio, saco (€), palet (€/t), granel volquete y cisterna (€/t)
- `data/avebiom_exw.csv`: mes y valor del índice en %. La app lo convierte a €/t con la base del 1T2019 (175,31 €/t, calculada a partir de marzo de 2023: 309,6 €/t = 176,6 %).

Se editan desde la web de GitHub con el lápiz ✏️.

> Los valores EXW mensuales se han leído del gráfico del PDF de octubre de 2026. Contrasta la correspondencia mes a mes con el PDF original.

## Configurar las alarmas
Todo está en `config/alertas.yaml`, con comentarios. Las alarmas disponibles son:

| Alarma | Salta cuando… |
|---|---|
| `variacion_punto` | un punto de venta sube o baja más de X % entre rondas |
| `variacion_media` | la media del mercado de un formato cambia más de X % |
| `desviacion_avebiom` | la media se aleja más de X % del último índice de AVEBIOM |
| `precio_objetivo` | algún punto baja de tu precio objetivo (saco, palet o granel) |
| `margen_origen_destino` | el diferencial destino − origen supera X €/t |
| `posible_fraude` | un precio está X % por debajo del índice. AVEBIOM alerta de webs falsas que suplantan a fabricantes reales |
| `sin_stock` | X o más puntos se quedan sin existencias |
| `fallo_scraper` | una web falla varias veces seguidas |
| `nuevo_indice_avebiom` | AVEBIOM publica un PDF nuevo |

`enfriamiento_dias` evita que la misma alarma se repita cada ronda.

## Añadir, quitar o arreglar puntos de venta
`config/fuentes.yaml` explica cada campo. Para **añadir** un punto, copia un bloque, pon la URL de la **página del producto** e indica `formato` y `kg`.

**Arreglar una fuente que falla:**
1. Si la web carga el precio con JavaScript, añade `playwright: true`.
2. Si encuentra un precio equivocado, abre la página en Chrome, haz clic derecho en el precio → *Inspeccionar*, copia la clase del elemento y añade `selector: ".esa-clase"`.
3. Si nada funciona (Amazon suele bloquear a los robots), pon `activo: false`.

**Webs descartadas a propósito:** durante la búsqueda aparecieron tiendas con palets a 200–300 € "con envío gratis", muy por debajo de cualquier precio real. Encajan con el patrón de webs fraudulentas del que avisa AVEBIOM y no se han incluido. Si añades una tienda nueva, la alarma `posible_fraude` te avisará si cae en ese rango.

## IVA
`config/ajustes.yaml` guarda el tipo de IVA por fechas. El pellet volvió al 21 % el 1 de julio de 2026, después de la rebaja temporal al 10 %. Si el Gobierno lo cambia, añade una línea con la fecha y el tipo nuevo.

## Ejecutarlo en tu ordenador (opcional)
```bash
pip install -r requirements.txt pytest
python -m playwright install chromium
python -m pytest              # pruebas
python -m pellet.main --sin-avisos            # una ronda sin enviar avisos
python -m pellet.main --solo lm-iberpellet-saco,caexven-saco   # probar algunas fuentes
python -m pellet.main --solo-panel            # rehacer el panel con los datos guardados
```

## Archivos
```
config/fuentes.yaml        puntos de venta vigilados
config/alertas.yaml        alarmas y canales
config/ajustes.yaml        IVA, pausas, correspondencias con AVEBIOM
data/precios.csv           histórico completo (una fila por punto y ronda)
data/avebiom_*.csv         índices de referencia
data/presupuestos_origen.csv  tus presupuestos de fábrica
data/estado.json           memoria de alarmas y fallos
docs/                      panel web (lo genera la app)
pellet/                    código
```

## Uso responsable
- Lee solo precios públicos, una vez cada dos días, con pausas entre peticiones, y respeta `robots.txt`.
- Revisa las condiciones de uso de cada web si vas a usar los datos con fines comerciales.
- Los índices de AVEBIOM son públicos y gratuitos. Cítalos como fuente si compartes el panel.

## Limitaciones conocidas
- Algunas grandes superficies muestran precios distintos según la tienda o el código postal. Se toma el precio que da la web por defecto.
- GitHub pausa las tareas programadas si un repositorio pasa 60 días sin actividad. Aquí no debería ocurrir, porque cada ronda guarda datos, pero si pasa basta con reactivarla en *Actions*.
- `*/2` en el calendario hace que a final de mes alguna vez se repita un día.
