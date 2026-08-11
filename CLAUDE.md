# Proyecto: Generador de Leads LinkedIn (n8n)

Pipeline híbrido de prospección B2B en México. Descubrimiento barato vía Serper
(índice de Google), enriquecimiento selectivo vía Apify, salida a Google Sheets.

Responde en español. Pasos numerados y directos. Sin explicaciones largas
cuando algo falla: dime qué se rompió y el fix.

---

## Estado actual

- `workflows/n8n_leads_linkedin_hibrido.json` — borrador original (credenciales
  placeholder). La version real corriendo en n8n vive como dos workflows
  (`hYpCuLqDEIutNwo4` y `IdUccT5jv7Kx4qOB`), mismo pipeline con distinto texto de
  formulario, ambos con credenciales reales configuradas.
- **Replica en Python lista y probada end-to-end** (`app.py` + `pipeline.py`,
  Flask en `http://localhost:5001`) — ver `README.md`. Corrida real de calibracion
  hecha, resultados en la seccion de Calibraciones abajo.
- `scripts/costos.py` — modelo de costo/tiempo. Los supuestos están en las primeras líneas.
- n8n corre en Docker en `http://localhost:5678`.
- n8n-mcp ya está configurado como MCP server en Claude Code.

## Arquitectura decidida

```
Form Trigger (puesto, ciudad, keywords, páginas)
  → Code: genera queries site:linkedin.com/in
  → HTTP: Serper /search        ← descubrimiento, ~$0.001/query
  → Code: parsea title, dedup por URL, score de relevancia
  → IF califica?
      true  → Code: lotes de 50 → HTTP: Apify → Code: normaliza → Sheets "Leads"
      false → Sheets "Descartados"
```

## Decisiones tomadas y por qué

**No se scrapea LinkedIn directo.** LinkedIn demandó a Proxycurl en enero 2025 y
la empresa cerró en julio de ese año. La línea legal es login vs. público: nada
que exija autenticación.

**Solo actors cookieless de Apify.** Los que piden cookie de sesión actúan como
tu cuenta y LinkedIn cierra sesión y advierte pasando ~500 perfiles/día. El
actor elegido (`supreme_coder~linkedin-profile-scraper`) no requiere login.

**Lotes de 50 hacia Apify.** El endpoint `run-sync-get-dataset-items` corta a los
300 s. 50 deja margen. Si el actor resulta lento, bajar a 25.

**`num=10` en Serper, no 100.** 1 crédito cubre hasta 10 resultados; 11–100
cuesta 2 créditos. Además Google retiró el parámetro `num=100` a fines de 2025,
así que pedir 100 puede cobrar doble y devolver 10.

## Tarifas verificadas (julio 2026 — reverificar antes de cotizar a cliente)

| Servicio | Tarifa |
|---|---|
| Serper | $0.001/query en paquete base $50/50k; baja a ~$0.0003 a volumen. Créditos expiran a 6 meses |
| Apify `supreme_coder~linkedin-profile-scraper` | $2 / 1,000 perfiles, sin cookies, 37 campos |
| Apify `harvestapi/linkedin-profile-search` | $0.10 / página de 25 + $0.004 / perfil completo |

Conclusión del modelo: el híbrido cuesta ~4.6x menos que Apify solo
($2.71 vs $12.35 por 1,000 leads calificados), pero tarda ~40% más de reloj
(34 vs 24 min) porque n8n serializa los lotes mientras Apify paraleliza interno.
El híbrido además tiene techo de recall: depende de lo que Google tenga indexado.

## Calibraciones — actualizado tras la replica en Python + corrida real

1. **Campo de input real del actor de Apify — RESUELTO.** No es `profileUrls`,
   es `urls` como arreglo de objetos `{"url": "..."}` (verificado contra el input
   schema real via `GET /v2/actor-builds/{id}` de la API de Apify). Ver
   `proyecto_leads_linkedin/pipeline.py::enriquecer_apify`.
2. **Tasa real de `parseo_ok`.** En una corrida de calibracion (Puesto="Gerente de
   Compras", Ciudad="Ciudad de Mexico", 1 pagina, sin keywords extra) califico 9/10.
   Mucho mas alto que el 20% asumido — pero es una muestra de 10 con busqueda de
   frase exacta en pagina 1 de Google, no generalizar todavia. Repetir con varios
   puestos/ciudades antes de fijar el numero del modelo de costos.
3. **Nombres de campo de salida del actor — parcialmente resuelto.** Con la
   corrida de calibracion: `titular`, `puesto_actual`, `empresa_actual`,
   `empresa_url`, `ubicacion`, `seguidores` llegan bien. `industria`,
   `tam_empresa` y `email` llegan vacios con la config actual del actor (requieren
   activar `scrapeCompany` / el addon `findContacts`, no estan prendidos).
4. **Confirmar cuántos `organic` devuelve Serper con `num=10` vs `num=100`.**
   Sigue sin probarse — no subir `num` sin correr esa prueba primero.

## Siguientes pasos

- [ ] Importar el workflow y sustituir los `PON_AQUI_TU_*` por Credentials de n8n
      (no dejar las keys en los nodos)
- [ ] Corrida de calibración: 1 página, rama Apify desconectada
- [ ] Ajustar umbral de `califica` según la tasa medida
- [ ] Corrida completa de 1 segmento real
- [ ] Aviso de privacidad LFPDPPP para el primer contacto (leads mexicanos =
      datos personales desde que tocan el Sheet)
- [ ] Decidir si se empaqueta como servicio recurrente

## Convenciones

- Salida a Sheets con `appendOrUpdate` matcheando por `url` — el workflow es
  idempotente, se puede recorrer el mismo segmento sin duplicar.
- Las URLs se normalizan quitando query string y slash final antes de dedup.
- Nunca commitear tokens. `.env` fuera de git.
