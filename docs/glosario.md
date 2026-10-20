# Glosario

Términos del proyecto que pueden no ser familiares para quien no viene de la estadística o del análisis
espacial. Cada uno tiene **qué es** y **por qué se usó**.

## Cobertura y caminata

**Cubierto.** Una persona está cubierta si vive a 15 minutos a pie o menos de una estación, caminando por las
calles y contando la pendiente.
*Por qué:* 15 minutos es un umbral habitual para el acceso a pie al transporte masivo. También se probó con
10 minutos para ver si las conclusiones cambian.

**Línea recta (buffer euclidiano).** La forma más simple de medir cercanía: se dibuja un círculo alrededor de
cada estación y se cuenta a la gente que vive dentro, sin importar calles, quebradas ni pendientes. Para
comparar en minutos, el radio es lo que se camina en 15 minutos en plano (unos 1,26 km).
*Por qué:* es el método que usan muchos estudios de cobertura. Se calcula para mostrar cuánto exagera: da
38,5 % de población cubierta, contra 24,9 % con calles y pendiente.

**Caminata plana.** Tiempo a pie por la red de calles real, pero suponiendo que el terreno es plano
(5,04 km/h).
*Por qué:* es el paso intermedio entre la línea recta y el cálculo completo. Permite separar cuánto de la
diferencia se debe a las calles (29,7 %) y cuánto a la pendiente (24,9 %).

**Pendiente.** Inclinación del terreno en el sentido en que se camina. Subir y bajar la misma cuesta no
cuesta lo mismo.
*Por qué:* La Paz y El Alto van de 3.000 a 4.600 m de altura; en las laderas, ignorar la pendiente hace
creer que mucha gente está más cerca de lo que está.

**Velocidad de Tobler (función de Tobler).** Fórmula que da la velocidad al caminar según la pendiente:
unos 5 km/h en plano, menos al subir y también al bajar cuestas muy empinadas.
*Por qué:* es la fórmula más usada para caminatas con pendiente y distingue subir de bajar, algo clave en
esta ciudad.

**Isócrona.** Área a la que se llega en un tiempo dado desde un punto, por ejemplo todo lo que queda a
15 minutos a pie de una estación.
*Por qué:* muestra en el mapa la cobertura real de cada estación, que no es un círculo sino una mancha
deformada por las calles y la pendiente.

**Dijkstra (multi-origen).** Algoritmo que encuentra el camino más corto en una red. "Multi-origen" quiere
decir que se calcula desde todas las estaciones a la vez.
*Por qué:* da en un solo cálculo el tiempo a pie de cada manzano a su estación más cercana, para los
32.860 manzanos.

**Grafo peatonal.** La red de calles, sendas y escaleras representada como puntos (esquinas) unidos por
tramos, cada uno con su tiempo de caminata. Es "dirigido" porque cada tramo tiene un tiempo de ida y otro de
vuelta.
*Por qué:* es la estructura que necesita Dijkstra para calcular tiempos por las calles reales.

## Datos y unidades espaciales

**Manzano.** La manzana del Censo 2024: la unidad más pequeña con población publicada.
*Por qué:* es el dato de población más detallado disponible; el tiempo a pie se calcula para cada uno.

**Hexágono H3.** Celda de una grilla de hexágonos que cubre el mapa (sistema H3, resolución 9: unos
0,1 km² cada uno).
*Por qué:* los manzanos tienen tamaños muy distintos y El Alto no tiene distritos completos en
OpenStreetMap. Los hexágonos dan una unidad pareja para sumar población, dibujar mapas y buscar estaciones.

**DEM (modelo digital de elevación).** Mapa de la altura del terreno; aquí, Copernicus GLO-30, con un dato
cada 30 m.
*Por qué:* de él sale la pendiente de cada tramo de calle.

**OSM (OpenStreetMap).** Mapa colaborativo y abierto del mundo.
*Por qué:* es la fuente abierta más completa de calles, sendas y escaleras de La Paz y El Alto.

**GTFS.** Formato estándar para publicar datos de transporte público: estaciones, líneas y recorridos.
*Por qué:* da la ubicación de las estaciones y qué líneas pasan por cada una.

**Abordaje.** Cada vez que alguien sube a una cabina. Un viaje con transbordo cuenta como dos abordajes.
*Por qué:* es la unidad en que Mi Teleférico publica sus "pasajeros"; se aclara para no confundirlo con
personas distintas.

**Cabecera.** Estación en el extremo de una línea. Las "cabeceras El Alto ↔ La Paz" son las de las líneas
que unen las dos ciudades (Roja, Amarilla y Morada).
*Por qué:* resultó ser lo que más explica la demanda de una estación (multiplica los abordajes por 6,7).

## Equidad

**Índice de vulnerabilidad (IV).** Número entre 0 y 1 que resume 7 carencias del censo para cada manzano
(0 = el menos carenciado, 1 = el más).
*Por qué:* permite preguntar no solo cuánta gente queda lejos, sino si es la que más necesita el transporte.

**Quintil.** Cada uno de los 5 grupos de igual población que resultan de ordenar a la gente por su IV. El
quintil 1 es el 20 % menos vulnerable; el 5, el 20 % más vulnerable.
*Por qué:* compara la cobertura entre grupos sociales: 44 % en el menos vulnerable frente a 6 % en el más.

**Percentil.** Posición de un valor dentro de un conjunto ordenado: estar en el percentil 50 es estar en la
mitad.
*Por qué:* se usa para construir el IV y para fijar qué hexágonos cuentan como densos.

**Brecha de accesibilidad.** Combinación de vulnerabilidad y lejanía: es alta donde vive gente vulnerable a
más de 30 minutos a pie.
*Por qué:* señala en el mapa dónde una estación nueva haría más por la equidad.

## Zonas sin cobertura

**Zona sin cobertura.** Grupo de hexágonos vecinos, densamente poblados y sin estación a 15 minutos.
Se numeran Z1, Z2… de mayor a menor población. En el código se llaman `bolson` o `bolsones`.
*Por qué:* convierte miles de hexágonos en 16 zonas concretas donde buscar estaciones nuevas.

**DBSCAN.** Método que agrupa puntos cercanos entre sí y deja fuera los aislados, sin decidir de antemano
cuántos grupos hay. Aquí cada hexágono pesa según su población.
*Por qué:* encuentra las zonas sin cobertura de forma automática y con cualquier forma, y descarta los
hexágonos sueltos que no justifican una estación.

**eps.** Distancia máxima para que DBSCAN considere vecinos a dos hexágonos (450 m).
*Por qué:* une hexágonos contiguos sin juntar barrios separados. Se probaron 350, 450 y 600 m.

**Núcleo.** Hexágono con al menos 6.000 personas sin cobertura a menos de `eps`; las zonas se forman a
partir de ellos.
*Por qué:* exige un mínimo de población para que una zona valga la pena.

**Robustez y persistencia.** Se repitió DBSCAN con 9 combinaciones de parámetros. La persistencia es la
fracción de combinaciones en que un hexágono cae dentro de alguna zona; solo se reportan las zonas que
aparecen en al menos la mitad.
*Por qué:* evita que el resultado dependa de un parámetro elegido a mano.

## Optimización de la nueva línea

**MCLP (problema de máxima cobertura).** Modelo que elige dónde poner *k* estaciones para que la mayor
cantidad posible de personas quede a 15 minutos o menos de alguna.
*Por qué:* responde directo a la pregunta del proyecto: dónde cubren más gente nueva las estaciones.

**p-mediana.** Modelo que elige dónde poner *k* estaciones para que el tiempo total de caminata de todos sea
el menor posible, aunque nadie quede dentro de los 15 minutos.
*Por qué:* es un segundo criterio para contrastar con el MCLP. Si los dos eligen lugares parecidos, la
propuesta es más sólida.

**Candidatos.** Lugares posibles para una estación nueva: centros de hexágonos habitados dentro de las zonas
sin cobertura y alrededor de ellas, con pendiente transitable.
*Por qué:* limitar las opciones a lugares razonables hace que la optimización sea posible en minutos.

**Búsqueda en haz.** Forma de armar la línea paso a paso: en cada paso se agregan estaciones posibles, se
guardan solo las 12 mejores líneas parciales y se sigue desde ellas.
*Por qué:* el MCLP elige puntos sueltos, pero un teleférico es una línea continua. Este método arma un
trazado conectado a la red actual sin probar todas las combinaciones, que serían demasiadas.

**Vano.** Tramo de cable entre dos estaciones (aquí, entre 700 y 2.500 m, con giros de 60° como máximo).
*Por qué:* refleja límites reales de un teleférico urbano: ni estaciones pegadas ni tramos imposibles.

**Personas por km.** Población nueva cubierta dividida por los km de cable.
*Por qué:* compara líneas de distinto largo. La propuesta rinde 16,2 mil personas por km, frente a
13,2 mil de la red actual.

## Modelo de demanda

**Binomial negativa.** Modelo estadístico para datos de conteo (aquí, abordajes por estación) cuando los
valores varían mucho entre unidades.
*Por qué:* los abordajes van de muy pocos a millones según la estación; un modelo de conteo más simple
(Poisson) subestimaría esa variación y daría intervalos demasiado estrechos.

**Validación leave-one-out (LOO).** Se ajusta el modelo 26 veces, dejando fuera una estación cada vez, y se
mide qué tan bien predice la que quedó fuera.
*Por qué:* con solo 26 estaciones no se puede separar un grupo de prueba. LOO mide el error con datos que el
modelo no vio y permite elegir entre modelos.

**Modelo nulo.** Modelo que predice lo mismo para todas las estaciones (el promedio).
*Por qué:* es la vara mínima: un modelo útil tiene que equivocarse menos que él (1,13 M frente a 3,13 M de
abordajes al año).

**Intervalo de confianza (IC 90 %).** Rango dentro del cual se espera el valor real con 90 % de
probabilidad, por ejemplo 5 a 14 M de abordajes al año.
*Por qué:* con tan pocas estaciones la estimación es incierta; el intervalo muestra cuánto.
