# -*- coding: utf-8 -*-

import os
import sys
import zipfile
import tablib
import codecs
from pymongo import MongoClient
import ConfigParser
import re
from datetime import datetime, date
import shutil
import tempfile
import pymongo

def parse_datetime(value, format="%Y%m%d"):
    # Funcio per l'add_formatter converteixi de string a datetime
    try:
        res = datetime.strptime(value, format)
    except:
        res = None
    return res

def parse_float(value):
    # Funcio per l'add_formatter converteixi valors en coma a float amb punt
    try:
        punts = value.replace(',', '.')
        deci = punts.split('.')[-1]
        nume = punts.split('.')[:-1]
        if nume:
            res = float('{}.{}'.format(''.join(nume), deci))
        else:
            res = value
    except:
        res = None
    return res

"""
Variables amb els tipus de consums
- comprovarem que sigui un dels dos valors 'x' in MAGNITUDS
- Sempre dividirem pel valor de la unitat consum/MAGNITUDS['x']
"""

MAGNITUDS = {
    'Wh': 1000,
    'kWh': 1
}


class Parsejador(object):
    # Variables estatiques
    directori = None
    dbname = None
    mongodb = None
    fitxer_conf = None
    filecodificat = None
    delimiter = None
    classe = None
    contador = None
    num_fields = None
    headers = None
    descartar = None
    primary_keys = None
    midafitxer = None
    flog = None
    pkeys = None
    tmpdir = None

    def __init__(self, directori=None, dbname=None):
        # Parser del fitxer de SIPS
        #Afagar els arxius de un directori
        self.directori = directori
        self.dbname = dbname

    def extreu_arxiu(self, tail, head, tmp_dir):
        """Mètode per descomprimir el zip"""
        arxiuex = open(head + '/' + tail, 'rb')
        z = zipfile.ZipFile(arxiuex)

        for name in z.namelist():
            z.extract(name, tmp_dir)
        arxiuex.close()
        return True

    def agafarxius(self, path):
        """Donat un directori retorna llista dels zips existents"""
        llista_arxius = []
        for fitxer in os.listdir(path):
            fparts = fitxer.split(".")
            print "fparts {}".format(fparts)
            if fparts[-1] == 'ZIP':
                llista_arxius.append(fitxer)
        return llista_arxius

    def insert_mongo(self, document, collection):
        # Afegeixo les entrades
        try:
            pvalues = [document[k] for k in self.pkeys]
            query = dict(zip(self.pkeys, pvalues))

            res = collection.update(query, document)
            if res['updatedExisting'] is False:
                collection.insert(document)
        except pymongo.errors.OpertionFailure:
            self.flog.write("Error: A l'insert del mongodb")

        return True

    def get_available_conf(self):
        """Aquest mètode retorna una llista amb tots els tipus de fitxers que
           podem carregar"""
        confs = []
        for fitxer in os.listdir("configs"):
            fparts = fitxer.split(".")
            confs.append(fparts[0])
        return confs

    def detectaconfservers(self, server):
        """Afagar directori i bbdd del fitxer de conf de servers"""
        for config in os.listdir("configs/servers"):
            conf = ConfigParser.RawConfigParser()
            conf.readfp(open("configs/servers/"+config))
            serverpat = conf.get('global', 'server')

            if serverpat == server:
                self.directori = conf.get('global', 'directori')
                self.dbname = conf.get('global', 'dbname')
                self.tmpdir = conf.get('global', 'tmp_dir')
            else:
                print "Error, no s'ha trobat cap coincidencia en les confs" \
                      "dels servidors"
                return False

        return True

    def detectaconf(self, arxiu):
        """Agafar la configuració corresponent dels fitxers de configuració"""
        head, tail = os.path.split(arxiu)

        for fitxer in os.listdir("configs"):
            conf = ConfigParser.RawConfigParser()
            try:
                conf.readfp(open("configs/"+fitxer))
            except IOError:
                continue
            pattern = conf.get('parser', 'pattern')
            # Coincideix el nom del fitxer amb camp de configuració
            if re.match(pattern, tail):
                self.fitxer_conf = fitxer

        if not self.fitxer_conf:
            return False
        else:
            return True

    def detectaconfselect(self, selector=None):
        """mètode alternatiu per trobar configuració, amb un selector"""

        for fitxer in os.listdir("configs"):
            conf = ConfigParser.RawConfigParser()
            try:
                conf.readfp(open("configs/"+fitxer))
            except IOError:
                continue
            nom_distri = conf.get('distri_name', 'pattern')
            # Buscar el nom de la distribuidora
            if nom_distri == selector:
                self.fitxer_conf = fitxer

        if not self.fitxer_conf:
            return False
        else:
            return True


    def load_conf(self, arxiu, directori, dirtmp=None):
        """Mètode per agafar valors de la configuració, crear un directori
        temporal """
        head, tail = os.path.split(arxiu)
        conf = ConfigParser.RawConfigParser()
        conf.readfp(open("configs/"+self.fitxer_conf))

        # Valors de la configuracio
        self.delimiter = conf.get('parser', 'delimiter')
        self.classe = conf.get('parser', 'class')
        self.headers = conf.items('fields')
        self.descartar = conf.options('descartar')
        self.primary_keys = conf.get('parser', 'primary_keys')
        self.pkeys = self.primary_keys.split(',')
        try:
            self.num_fields = conf.get('parser', 'num_fields')
        except:
            self.num_fields = False

        # Crear directori temporal
        try:
            tmp_dir = tempfile.mkdtemp(dir=dirtmp)
            self.extreu_arxiu(tail, directori, tmp_dir)
            # Buscar el fitxer extret
            for (path, dirs, files) in os.walk(tmp_dir):
                if files:
                    # Guardar el fitxer i la mida
                    self.filecodificat = codecs.open(path+'/'+files[0], "r",
                                                     "iso-8859-15")
                    self.midafitxer = os.stat(path+'/'+files[0]).st_size
        except Exception as e:
            self.flog.write("Error: a la extració del zip, info: {}"
                            .format(e.message))
            # Borrar el directori temporal
            shutil.rmtree(tmp_dir)
            raise SystemExit
        finally:
            try:
                # Borrar el directori temporal
                shutil.rmtree(tmp_dir)
            except OSError as exc:
                if exc.errno != 2:
                    raise SystemExit

        return True

    def connectamongo(self):
        try:
            # Connectar i escollir la bbdd
            client = MongoClient()
            # Base de dades
            self.mongodb = client[self.dbname]
        except Exception as e:
            self.flog.write("Error: No s'ha pogut connectar a la base de dades,"
                            "info: {}".format(e.message))
            raise SystemExit
        return self.mongodb

    def carregar_mongo(self):
        # Camps del conf
        headers_conf = [h[0] for h in self.headers]
        valores = [h[1] for h in self.headers]
        vals = [v.split() for v in valores]
        vals_tipus = [v[0] for v in vals]
        vals_apa = [v[1] for v in vals]
        try:
            vals_mag = [v[2] for v in vals]
        except:
            vals_mag = []

        # Contador de linies
        count = 0
        # Per calcular la progressió
        sumatori = 0
        # Usuari del mongodb
        user = 'default'

        # Afago la coleccio que vull
        if self.classe == 'giscedata_sips_ps':
            collection = self.mongodb.giscedata_sips_ps
        elif self.classe == 'giscedata_sips_consums':
            collection = self.mongodb.giscedata_sips_consums
        else:
            self.flog.write("Error: No es reconeix la collection {}"
                            .format(self.classe))
            raise SystemExit

        # Comprovo que la collecció estigui creada, si no la creo
        if not self.mongodb['counters'].count():
            self.mongodb['counters'].save({"_id": self.classe, "counter": 1})

        #Creo el dataset buit
        data = tablib.Dataset()
        data.headers = headers_conf

        # Millores: posar la cadena de lambda al fitxer de conf
        for he, v in zip(self.headers, vals_tipus):
            if v == 'float':
                data.add_formatter(he[0],
                                   lambda a: a and parse_float(a) or 0)
            if v == 'integer':
                data.add_formatter(he[0],
                                   lambda a:
                                   a and int(parse_float(a)) or 0)
            if v == 'datetime':
                data.add_formatter(he[0], parse_datetime)
            if v == 'long':
                data.add_formatter(he[0],
                                   lambda a: a and long(a) or 0)

        # Passar a kW les potencies que estan en W
        for he, v in zip(self.headers, vals_mag):
            if v == 'Wh':
                data.add_formatter(he[0],
                                   lambda a:
                                   a and float(a)/MAGNITUDS['Wh']
                                   or 0)
            elif v == 'kWh':
                data.add_formatter(he[0],
                                   lambda a:
                                   a and float(a)/MAGNITUDS['kWh']
                                   or 0)

        # Crear index per les primary_keys
        if self.classe == 'giscedata_sips_ps':
            self.mongodb.eval("""db.giscedata_sips_ps.ensureIndex(
                {"name": 1},
                {"background": true})""")

        elif self.classe == 'giscedata_sips_consums':
            self.mongodb.eval("""db.giscedata_sips_consums.ensureIndex(
                {"name": 1},
                {"background": true})""")
        else:
            self.flog.write("Error: En fer l'index {}"
                            )
            raise SystemExit

        # Llegeixo per tot el fitxer
        while self.filecodificat.tell() < self.midafitxer:
            # Tracto les dades del fitxer linia per linia
            linia = self.filecodificat.readline()
            slinia = tuple(linia.split(self.delimiter))
            slinia = map(lambda s: s.strip(), slinia)

            # Contador del tros de la linia
            contadorlinia = 0
            # Llista de les posicions de les capçaleres segons la configuració
            position = [eval(num, {"n": contadorlinia}) for num in vals_apa]
            # Itero per els trossos de la linia
            for i in range(0, len(slinia), len(position)):
                try:
                    # Llista dels valors del tros que agafem dins la linia
                    datal = [slinia[p] for p in position]
                    data.append(datal)

                    if self.num_fields and len(datal) != int(self.num_fields):
                        self.flog.write("Longitud de la fila {} incorrecte\n"
                                        "len_data:{}, self.num_fields:{}"
                                        .format(count, len(datal),
                                                self.num_fields))

                    # Borro les claus que em surt l'arxiu de configuracio
                    for d in self.descartar:
                        del data[d]
                    # Creo el diccionari per fer l'insert al mongo
                    document = data.dict[0]

                    # Id incremental
                    counter = self.mongodb['counters'].find_and_modify(
                        {'_id': self.classe},
                        {'$inc': {'counter': 1}})

                    # Update del index
                    document.update(
                        {'id': counter['counter'],
                         'create_uid': user,
                         'create_date': datetime.now()}
                    )

                    # Inserto el document al mongodb
                    self.insert_mongo(document, collection)
                    #Borrar els valors del tros
                    data.wipe()
                    #Torno a establir les capçaleres
                    data.headers = headers_conf
                except Exception as e:
                    self.flog.write("Error a la fila {}, "
                                    "info: {}\n".format(count, e.message))
                    #Faig el wipe per no extendre l'error
                    data.wipe()
                    #Torno a establir les capçaleres
                    data.headers = headers_conf
                # Actualizo el contador i les posicions
                contadorlinia += 1
                position = [eval(num, {"n": contadorlinia}) for num in
                            vals_apa]
            # Actualitzo contador de linies, sumatori i tantpercert completat
            count += 1
            sumatori += len(linia)
            tantpercent = float(sumatori) / self.midafitxer * 100.0

            sys.stdout.write("\r%d%%" % int(tantpercent))
            sys.stdout.flush()

        print "\nNumero de linies: {}".format(count)
        return True

    def parser(self, arxiu, directori, conf=False):
        # Si ve conf comprovar que sigui una opció possible
        if conf not in self.get_available_conf() and conf:
            self.flog.write("Error, la configuració {} que ha entrat no es "
                            "troba als fitxers de configuració".format(conf))
            raise SystemExit
        # Si no passem cap configuracio predeterminada
        if not conf:
            if self.detectaconf(arxiu):
                self.load_conf(arxiu, directori)
                self.carregar_mongo()
            else:
                self.flog.write("Error, No s'ha trobat el fitxer de "
                                "configuració correcte de forma automatica")
        return True

    def run(self):
        llista_arxius = self.agafarxius(self.directori)
        # Processar per cada un dels arxius zip
        for arxiu in llista_arxius:
            # Log per els errors de lectura
            print "Arxiu:{}".format(arxiu)
            self.flog = open(arxiu + ".txt", "w")

            try:
                if self.connectamongo():
                    self.parser(arxiu, self.directori)
                self.flog.write("Fitxer finalitzat")
            except:
                self.flog.write("Hi ha hagut algun error")

            self.flog.close()
