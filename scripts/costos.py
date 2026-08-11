# Modelo con las tarifas verificadas en julio 2026
SERPER_Q       = 0.001    # USD por query (paquete base $50/50k). Baja a 0.0003 a volumen
SERPER_YIELD   = 7        # URLs /in/ unicas utiles por query (10 organic - ruido - dedup)
APIFY_ENRICH   = 0.002    # supreme_coder, $2/1k perfiles, sin cookies
APIFY_PAGE     = 0.10     # harvestapi, por pagina de busqueda (25 resultados)
APIFY_FULL     = 0.004    # harvestapi, por perfil completo

TASA_HIB   = 0.20   # % que califica saliendo del indice de Google (ruidoso)
TASA_APIFY = 0.65   # % que califica usando filtros nativos de LinkedIn

def hibrido(objetivo_calificados):
    descubrir = objetivo_calificados / TASA_HIB
    queries   = descubrir / SERPER_YIELD
    c_desc    = queries * SERPER_Q
    c_enr     = objetivo_calificados * APIFY_ENRICH
    lotes     = -(-objetivo_calificados // 50)
    seg       = (queries / 5) * 1.5 + lotes * 90
    return descubrir, queries, c_desc, c_enr, c_desc + c_enr, seg

def apify_solo(objetivo_calificados):
    scrapear = objetivo_calificados / TASA_APIFY
    paginas  = -(-scrapear // 25)
    c_desc   = paginas * APIFY_PAGE
    c_enr    = scrapear * APIFY_FULL
    seg      = 45 + scrapear * 0.9      # 1 solo run, paralelizado en la nube de Apify
    return scrapear, paginas, c_desc, c_enr, c_desc + c_enr, seg

print(f"{'Calif.':>7} | {'HIBRIDO $':>10} {'min':>5} | {'APIFY $':>9} {'min':>5} | {'ahorro':>7}")
print("-"*58)
for n in (200, 500, 1000, 5000):
    h = hibrido(n); a = apify_solo(n)
    print(f"{n:>7} | {h[4]:>10.2f} {h[5]/60:>5.1f} | {a[4]:>9.2f} {a[5]/60:>5.1f} | {a[4]/h[4]:>6.1f}x")

print()
n = 1000
h = hibrido(n); a = apify_solo(n)
print(f"Desglose para {n} leads calificados y enriquecidos:")
print(f"  HIBRIDO : descubre {h[0]:.0f} perfiles con {h[1]:.0f} queries")
print(f"            Serper ${h[2]:.2f} + Apify ${h[3]:.2f} = ${h[4]:.2f}")
print(f"            costo por lead calificado: ${h[4]/n:.5f}")
print(f"  APIFY   : scrapea {a[0]:.0f} perfiles en {a[1]:.0f} paginas de busqueda")
print(f"            busqueda ${a[2]:.2f} + perfiles ${a[3]:.2f} = ${a[4]:.2f}")
print(f"            costo por lead calificado: ${a[4]/n:.5f}")
print()
print("Serper solo (sin enriquecer), 1000 calificados:")
print(f"  ${hibrido(n)[2]:.2f}  -> pero con 4 campos, no 37")
