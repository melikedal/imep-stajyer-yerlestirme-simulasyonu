import random
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pandas as pd
import numpy as np
import time
import json
import os
import subprocess
import sys

try:
    import openpyxl
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl

# ------------------------------------------------------------
# 1. PUANLAMA / MEMNUNİYET
# ------------------------------------------------------------

def memnuniyet_puani(ogrenci):
    if ogrenci["atanan_firma"] == -1:
        return 0
    try:
        # Tercih listesindeki sırasına göre puan ver (1. tercih=5, 5. tercih=1)
        idx = ogrenci["tercihler"].index(ogrenci["atanan_firma"])
        return 5 - idx
    except:
        return 0 # Tercih dışı (Resen/Ek Kontenjan) atama

# ------------------------------------------------------------
# 2. VERİ ÜRET / OKU
# ------------------------------------------------------------

def veri_uret(firma_sayisi, ogrenci_sayisi, tohum, csv_yolu, json_yolu):
    np.random.seed(tohum)
    random.seed(tohum)

    if not os.path.exists(csv_yolu) or not os.path.exists(json_yolu):
        raise FileNotFoundError("Dosyalar bulunamadı!")

    firmalar_full = pd.read_csv(csv_yolu)
    firmalar = firmalar_full.head(firma_sayisi).copy()

    temel = ogrenci_sayisi // firma_sayisi
    artik = ogrenci_sayisi % firma_sayisi
    firmalar["kapasite"] = temel
    for i in range(artik):
        firmalar.at[firmalar.index[i], "kapasite"] += 1
    firmalar["kalan"] = firmalar["kapasite"]

    with open(json_yolu, "r", encoding="utf-8") as f:
        ogr_liste = json.load(f)
    ogrenciler = pd.DataFrame(ogr_liste[:ogrenci_sayisi])

    # GNO'ya göre sıralamalar
    ogrenciler = ogrenciler.sort_values(by="gno", ascending=False)

    for i, (idx, _) in enumerate(ogrenciler.iterrows()):
        ogr_gno = float(ogrenciler.at[idx, "gno"])
        uygun_f_df = firmalar[firmalar["gno_sarti"] <= ogr_gno]
        uygun_firmalar = uygun_f_df.index.tolist()
        
        # Puanı yetenleri GNO şartına göre sırala (Yüksekten düşüğe)
        uygun_sirali = uygun_f_df.sort_values(by="gno_sarti", ascending=False).index.tolist()
        
        if len(uygun_firmalar) >= 15:
            # ÜST LİG: Hem kaliteli yerleri hem de orta seviyeleri yazsın
            hayal = random.sample(uygun_sirali[:10], 3)
            garanti = random.sample(uygun_sirali[10:20], 2)
            ogrenciler.at[idx, "tercihler"] = hayal + garanti
            
        elif len(uygun_firmalar) >= 5:
            # ALT LİG: Puanı az yere yetenler, o yerlerin EN DÜŞÜK ŞARTLI olanlarını kesin yazmalı
            # Son 3 tercihi mutlaka GNO şartı en düşük firmalar olsun (Sigorta)
            en_garanti = uygun_sirali[-3:]
            digerleri = random.sample(uygun_sirali[:-3], 2) if len(uygun_sirali) > 3 else random.sample(uygun_sirali, 2)
            ogrenciler.at[idx, "tercihler"] = digerleri + en_garanti
            
        else:
            # KRİTİK GRUP: Puanı 5'ten az yere yetenler
            # Bu öğrencileri sistemde boş kalması en muhtemel firmalara zorla yönlendiriyoruz
            en_dusukler = firmalar.sort_values(by="gno_sarti", ascending=True).index.tolist()
            mevcut = uygun_firmalar.copy()
            k = 0
            while len(mevcut) < 5:
                if en_dusukler[k] not in mevcut:
                    mevcut.append(en_dusukler[k])
                k += 1
            ogrenciler.at[idx, "tercihler"] = mevcut

    ogrenciler["atanan_firma"] = -1
    ogrenciler["yerlesme_turu"] = "-"
    return ogrenciler, firmalar

def greedy_turu(ogrenciler, firmalar, tur_no, log_func):
    islem = 0
    yerlesen = 0
    bos_idx = ogrenciler[ogrenciler["atanan_firma"] == -1].index.tolist()
    
    for idx in bos_idx:
        ogr = ogrenciler.loc[idx]
        log_func(f"\n> {ogr['ad']} (GNO: {ogr['gno']})\n", "tur")
        log_func("  Başvurular:\n")
        
        yerlesme_oldu = False
        for sira, fid in enumerate(ogr["tercihler"], 1):
            islem += 1
            f_ad = firmalar.at[fid, "ad"]
            f_sart = float(firmalar.at[fid, "gno_sarti"])
            
            if float(ogr["gno"]) < f_sart:
                log_func(f"    {f_ad:<20} -> RED    (GNO Yetersiz: {f_sart:.2f})\n")
            elif int(firmalar.at[fid, "kalan"]) <= 0:
                log_func(f"    {f_ad:<20} -> RED    (Kontenjan Dolu)\n")
            else:
                # KABUL DURUMU
                firmalar.at[fid, "kalan"] -= 1
                ogrenciler.at[idx, "atanan_firma"] = fid
                ogrenciler.at[idx, "yerlesme_turu"] = f"{tur_no}. Tur"
                yerlesen += 1
                yerlesme_oldu = True
                puan = 5 - (sira - 1)
                log_func(f"    {f_ad:<20} -> KABUL \u2705 ({sira}. Tercih) | Puan: {puan}\n", "kabul")
                break
        
        if not yerlesme_oldu:
            log_func("  \u279c Bu turda yerleşemedi.\n", "red")

    return yerlesen, islem

# ------------------------------------------------------------
# 4. HEURİSTİK TURU
# ------------------------------------------------------------

def heuristik_turu(ogrenciler, firmalar, tur_no, log_func):
    islem = 0
    yerlesen = 0
    bos_idx = ogrenciler[ogrenciler["atanan_firma"] == -1].index.tolist()

    # Öğrenci bazlı detaylı log (Greedy ile aynı format)
    for idx in bos_idx:
        ogr = ogrenciler.loc[idx]
        log_func(f"\n> {ogr['ad']} (GNO: {ogr['gno']})\n", "tur")
        log_func("  Başvurular:\n")

        aday_kabul = [] #aday havuzu oluşturma

        for sira, fid in enumerate(ogr["tercihler"], 1):
            islem += 1
            f_ad = firmalar.at[fid, "ad"]
            f_sart = float(firmalar.at[fid, "gno_sarti"])

            if float(ogr["gno"]) < f_sart:
                log_func(f"    {f_ad:<20} -> RED    (GNO Yetersiz: {f_sart:.2f})\n")
                continue

            if int(firmalar.at[fid, "kalan"]) <= 0:
                log_func(f"    {f_ad:<20} -> RED    (Kontenjan Dolu)\n")
                continue

            skor = (5 - (sira - 1)) * 10 + (float(ogr["gno"]) * 2) #liyakat formulu
            log_func(
                f"    {f_ad:<20} -> ADAY   "
                f"({sira}. Tercih | Skor: {skor:.1f})\n",
                "info"
            )
            aday_kabul.append((skor, fid, sira))

        if aday_kabul:
            # En iyi skoru seç
            aday_kabul.sort(reverse=True, key=lambda x: x[0])
            skor, fid, sira = aday_kabul[0]

            firmalar.at[fid, "kalan"] -= 1
            ogrenciler.at[idx, "atanan_firma"] = fid
            ogrenciler.at[idx, "yerlesme_turu"] = f"{tur_no}. Tur"
            yerlesen += 1

            puan = 5 - (sira - 1)
            log_func(
                f"  ➜ {firmalar.at[fid,'ad']} -> KABUL ✅ "
                f"({sira}. Tercih | Skor: {skor:.1f} | Puan: {puan})\n",
                "kabul"
            )
        else:
            log_func("  ➜ Bu turda yerleşemedi.\n", "red")

    return yerlesen, islem

    # ------------------------------------------------------------
# LOCAL SEARCH – SADECE EK
# ------------------------------------------------------------

def local_search_iyilestir(ogrenciler, log_func, deneme_sayisi=200):

    

    def toplam_memnuniyet():
        return sum(memnuniyet_puani(row) for _, row in ogrenciler.iterrows())

    en_iyi = toplam_memnuniyet()
    atanmislar = ogrenciler[ogrenciler["atanan_firma"] != -1].index.tolist()

    if len(atanmislar) < 2:
        return

    for _ in range(deneme_sayisi):
        i1, i2 = random.sample(atanmislar, 2)

        f1 = ogrenciler.at[i1, "atanan_firma"]
        f2 = ogrenciler.at[i2, "atanan_firma"]

        if f1 == f2:
            continue

        # dene
        ogrenciler.at[i1, "atanan_firma"] = f2
        ogrenciler.at[i2, "atanan_firma"] = f1

        yeni = toplam_memnuniyet()

        if yeni < en_iyi:
            # geri al
            ogrenciler.at[i1, "atanan_firma"] = f1
            ogrenciler.at[i2, "atanan_firma"] = f2
        else:
         log_func(
        f"[LOCAL SEARCH] "
        f"{ogrenciler.at[i1, 'ad']} ↔ "
        f"{ogrenciler.at[i2, 'ad']} | "
        f"{en_iyi} → {yeni}\n",
        "info"
    )
    en_iyi = yeni


    

# ------------------------------------------------------------
# 5. RED UYGULAMA
# ------------------------------------------------------------

def red_uygula(ogrenciler, firmalar, red_orani, log_func):
    toplam_red = 0
    atanmislar = ogrenciler[ogrenciler["atanan_firma"] != -1].index.tolist()
    
    for idx in atanmislar:
        if random.random() < red_orani:
            fid = ogrenciler.at[idx, "atanan_firma"]
            f_ad = firmalar.at[fid, "ad"]
            ogr_ad = ogrenciler.at[idx, "ad"]
            
            # Kayıtları sıfırla
            ogrenciler.at[idx, "atanan_firma"] = -1
            ogrenciler.at[idx, "yerlesme_turu"] = "-"
            firmalar.at[fid, "kalan"] += 1
            toplam_red += 1
            log_func(f"  ! {ogr_ad} -> {f_ad} RED \u2716 (Firma Reddi)\n", "red")

    return toplam_red

# ------------------------------------------------------------
# 6. SİMÜLASYON MOTORU
# ------------------------------------------------------------

def simulasyon_motoru(yontem, ogrenciler, firmalar, red_orani, log_func, swap_log=None):
    start_time = time.time()
    toplam_islem = 0
    tur = 0

    # 1. AŞAM: Tercihlere Göre Yerleştirme (Dinamik Tur Sayısı)
    while (ogrenciler["atanan_firma"] == -1).any():
        tur += 1
        log_func(f"\n{'#'*60}\n# {tur:02d}. İTERASYON ({yontem.upper()})\n{'#'*60}\n", "tur")

        if yontem == "greedy":
            yerlesen, islem = greedy_turu(ogrenciler, firmalar, tur, log_func)
        else:
            yerlesen, islem = heuristik_turu(ogrenciler, firmalar, tur, log_func)

        toplam_islem += islem
        log_func(f"\n✅ Bu iterasyonda yerleştirilen: {yerlesen}\n", "kabul")

        # Red Mekanizması (Burada tek sefer çağrılması yeterli)
        etkin_red = red_orani * (0.90 ** (tur - 1)) if tur < 20 else 0
        toplam_red = red_uygula(ogrenciler, firmalar, etkin_red, log_func)
        if toplam_red > 0:
            log_func(f"❌ Toplam {toplam_red} öğrenci firma reddi aldı.\n", "red")

        # DÖNGÜYÜ KIRMA ŞARTI: 
        # Eğer bu turda kimse yerleşmediyse VE kimse red alıp boşa çıkmadıysa tıkanma olmuştur.
        if yerlesen == 0 and toplam_red == 0:
            log_func("\n⚠️ Tercihlerle yerleşme tıkandı, ek kontenjana geçiliyor.\n", "red")
            break
            
        if tur > 100: # Güvenlik sınırı
            break

    # 2. AŞAM: Ek Kontenjan (WHILE DÖNGÜSÜNÜN DIŞINDA!)
    # Sadece turlar bittikten sonra hala açıkta kalan varsa çalışır.
    acikta = ogrenciler[ogrenciler["atanan_firma"] == -1].index.tolist()
    if acikta:
        log_func(f"\n📢 {len(acikta)} öğrenci tercih dışı yerleştiriliyor...\n", "info")
        for idx in acikta:
            uygun_f = firmalar[firmalar["kalan"] > 0].index.tolist()
            if uygun_f:
                fid = random.choice(uygun_f)
                firmalar.at[fid, "kalan"] -= 1
                ogrenciler.at[idx, "atanan_firma"] = fid
                ogrenciler.at[idx, "yerlesme_turu"] = "Ek Kontenjan"
                log_func(f"  {ogrenciler.at[idx,'ad']} -> {firmalar.at[fid,'ad']} (Ek Kontenjan Ataması)\n", "info")

    if not (ogrenciler["atanan_firma"] == -1).any():
        log_func("\n🎉 Tüm öğrenciler yerleşti!\n", "kabul")

    if yontem == "heuristik":
        local_search_iyilestir(ogrenciler, log_func)
        
    end_time = time.time()
    return {
        "islem": toplam_islem,
        "memnuniyet": sum(memnuniyet_puani(row) for _, row in ogrenciler.iterrows()),
        "sure": round(end_time - start_time, 4),
        "tur": tur
    }
    

# ------------------------------------------------------------
# 7. GUI 
# ------------------------------------------------------------

class BTU_App(tk.Tk):
    
    

    
    def __init__(self):
        super().__init__()
        self.title("BTÜ İMEP - STAJYER YERLEŞTİRME SİMÜLASYONU")
        self.geometry("1300x850")
        self.configure(bg="#f0f2f5")
        self.csv_path = None
        self.json_path = None
        self.son_ogrenciler = None
        self.son_firmalar = None
        self._style_ayarla()
        self._arayuz_kur()

    def raporu_disa_aktar(self):
        if self.son_ogrenciler is None or self.son_firmalar is None:
            messagebox.showwarning("Uyarı", "Önce bir simülasyon çalıştırmalısınız!")
            return

        dosya_yolu = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel Dosyası", "*.xlsx"), ("CSV Dosyası", "*.csv")],
            title="Yerleştirme Raporunu Kaydet",
            initialfile=f"IMEP_Yerlestirme_Raporu_{self.combo.get()}"
        )

        if dosya_yolu:
            try:
                rapor_df = self.son_ogrenciler.copy()
                
                # Firma ID'lerini isimlere çevir
                rapor_df["Atanan_Firma"] = rapor_df["atanan_firma"].apply(
                    lambda x: self.son_firmalar.at[x, "ad"] if x != -1 else "Yerleşemedi"
                )
                
                # Memnuniyet puanı fonksiyonunu kullanarak ekle
                rapor_df["Memnuniyet_Puani"] = rapor_df.apply(memnuniyet_puani, axis=1)

                if dosya_yolu.endswith(".xlsx"):
                    rapor_df.to_excel(dosya_yolu, index=False)
                else:
                    rapor_df.to_csv(dosya_yolu, index=False, encoding="utf-8-sig")

                messagebox.showinfo("Başarılı", f"Rapor başarıyla kaydedildi:\n{dosya_yolu}")
            except Exception as e:
                messagebox.showerror("Hata", f"Kaydedilirken hata oluştu: {e}")    

    def _style_ayarla(self):
        style = ttk.Style()
        style.theme_use("clam")
        # SATIR YÜKSEKLİĞİNİ BURADAN AYARLIYORUZ (İsimlerin sığması için 100 yaptık)
        style.configure("Treeview", rowheight=100) 
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#003366", foreground="white")
        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[35, 10], width=35)
        style.configure("My.TCombobox", font=("Segoe UI", 13))

    def _arayuz_kur(self):
        header = tk.Frame(self, bg="#003366", height=70)
        header.pack(fill="x")
        tk.Label(header, text="İMEP STAJYER YERLEŞTİRME SİMÜLASYONU", fg="white", bg="#003366", font=("Segoe UI", 16, "bold")).pack(pady=18)

        body = tk.Frame(self, bg="#f0f2f5")
        body.pack(fill="both", expand=True, padx=20, pady=20)

        sidebar = tk.Frame(body, bg="white", width=280, highlightthickness=1, highlightbackground="#d1d5db", padx=20, pady=20)
        sidebar.pack(side="left", fill="y", padx=(0, 20))
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="SİMÜLASYON AYARLARI", font=("Segoe UI", 11, "bold"), fg="#003366", bg="white").pack(pady=(0, 10))

        self.entries = {}
        ayarlar = [("Firma Sayısı", "30"), ("Öğrenci Sayısı", "150"), ("Seed:", "42"), ("Red Oranı:", "0.15")]
        for lbl, dlt in ayarlar:
            tk.Label(sidebar, text=lbl, bg="white", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(2, 0))
            e = ttk.Entry(sidebar, font=("Segoe UI", 11))
            e.insert(0, dlt)
            e.pack(fill="x", pady=(0, 2), ipady=2)
            self.entries[lbl] = e

        self.combo = ttk.Combobox(sidebar, values=["Greedy", "Heuristik", "İkisini Karşılaştır"], state="readonly", style="My.TCombobox", font=("Segoe UI", 11))
        self.combo.set("Greedy")
        self.combo.pack(fill="x", pady=(5, 15), ipady=4)

        self.btn_csv = tk.Button(sidebar, text="📁 Firma Listesi (.csv)", command=self.csv_sec, bg="#e2e8f0", relief="flat")
        self.btn_csv.pack(fill="x", pady=2)
        self.btn_json = tk.Button(sidebar, text="📁 Öğrenci Listesi (.json)", command=self.json_sec, bg="#e2e8f0", relief="flat")
        self.btn_json.pack(fill="x", pady=(2, 20))

        tk.Button(sidebar, text="▶ ANALİZİ BAŞLAT", bg="#00a8a8", fg="white", font=("Segoe UI", 13, "bold"), command=self.calistir, relief="flat", pady=16).pack(fill="x")
        # Raporlama Butonu
        self.btn_export = tk.Button(
            sidebar, 
            text="📥 SONUÇLARI DIŞA AKTAR", 
            bg="#2c3e50", 
            fg="white", 
            font=("Segoe UI", 11, "bold"),
            command=self.raporu_disa_aktar, # Sınıfa eklediğin fonksiyonu burada çağırdık
            relief="flat", 
            pady=10
        )
        self.btn_export.pack(fill="x", pady=(10, 0))
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(side="left", fill="both", expand=True)

        self.tab_log = tk.Frame(self.tabs, bg="white")
        self.tab_firma = tk.Frame(self.tabs, bg="white")
        self.tab_res = tk.Frame(self.tabs, bg="white")
        self.tab_compare = tk.Frame(self.tabs, bg="#f8f9fa")

        self.tabs.add(self.tab_log, text=" 📜 Simülasyon Günlüğü ")
        self.tabs.add(self.tab_firma, text=" 🏢 Firma Durumları ")
        self.tabs.add(self.tab_res, text=" 📊 Öğrenci Sonuçları ")
        self.tabs.add(self.tab_compare, text=" ⚖️ Karşılaştırma Analizi ")

        log_container = tk.Frame(self.tab_log, bg="white")
        log_container.pack(fill="both", expand=True)
        sc_y = ttk.Scrollbar(log_container, orient="vertical")
        sc_y.pack(side="right", fill="y")
        self.txt_log = tk.Text(log_container, font=("Consolas", 10), bg="#fafafa", relief="flat", wrap="none", yscrollcommand=sc_y.set)
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=10)
        sc_y.config(command=self.txt_log.yview)

        self.txt_log.tag_config("tur", foreground="#003366", font=("Consolas", 11, "bold"))
        self.txt_log.tag_config("kabul", foreground="#2e7d32", font=("Consolas", 10, "bold"))
        self.txt_log.tag_config("red", foreground="#d32f2f")
        self.txt_log.tag_config("info", foreground="#e67e22", font=("Consolas", 10, "bold"))

        self._karsilastirma_ekrani_hazirla()
        # Firma tablosu sütun isimlerini belirledik
        self.tree_firma = self._tree_kur(self.tab_firma, ("AD", "GNO ŞARTI", "KAPASİTE", "KALAN", "YERLEŞENLER"))
        self.tree_res = self._tree_kur(self.tab_res, ("ÖĞRENCİ", "GNO", "TUR", "FİRMA", "PUAN"))

    def _tree_kur(self, parent, cols):
        # Arama Alanı (Eklendi)
        search_frame = tk.Frame(parent, bg="white")
        search_frame.pack(fill="x", padx=15, pady=5)
        tk.Label(search_frame, text="🔍 Filtrele:", bg="white", font=("Segoe UI", 9, "bold")).pack(side="left")
        
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # Tablo Alanı
        tree = ttk.Treeview(parent, columns=cols, show="headings")
        # Filtreleme fonksiyonunu bağla
        search_var.trace("w", lambda *args: self._tablo_filtrele(tree, search_var.get()))
        
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=400 if c == "YERLEŞENLER" else 150, anchor="center")
        
        sc_tree = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sc_tree.set)
        sc_tree.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True, padx=15, pady=5)
        return tree

    def _karsilastirma_ekrani_hazirla(self):
        self.frame_g = tk.LabelFrame(self.tab_compare, text=" GREEDY SONUÇLARI ", font=("Segoe UI", 12, "bold"), bg="white", padx=25, pady=25)
        self.frame_g.place(relx=0.05, rely=0.1, relwidth=0.42, relheight=0.7)
        self.frame_h = tk.LabelFrame(self.tab_compare, text=" HEURİSTİK SONUÇLARI ", font=("Segoe UI", 12, "bold"), bg="white", padx=25, pady=25)
        self.frame_h.place(relx=0.53, rely=0.1, relwidth=0.42, relheight=0.7)

        self.comp_labels = {}
        for name, frame in [("greedy", self.frame_g), ("heuristik", self.frame_h)]:
            labels = []
            for txt in ["Memnuniyet Puanı: -", "Çözüm Süresi: -", "İşlem Sayısı: -", "Tur Sayısı: -"]:
                lbl = tk.Label(frame, text=txt, bg="white", font=("Segoe UI", 11))
                lbl.pack(pady=10)
                labels.append(lbl)
            self.comp_labels[name] = labels

    def _update_comp(self, name, r):
        l1, l2, l3, l4 = self.comp_labels[name]
        l1.config(text=f"Memnuniyet Puanı: {r['memnuniyet']}", fg="#1a73e8")
        l2.config(text=f"Çözüm Süresi: {r['sure']} sn")
        l3.config(text=f"İşlem Sayısı: {r['islem']}")
        l4.config(text=f"Tur Sayısı: {r['tur']}")

    def csv_sec(self):
        yol = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if yol: self.csv_path = yol; self.btn_csv.config(text="✅ Yüklendi", fg="green")

    def json_sec(self):
        yol = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if yol: self.json_path = yol; self.btn_json.config(text="✅ Yüklendi", fg="green")

    def swap_gui_yaz(self, metin):
        self.swap_text.insert("end", metin + "\n")
        self.swap_text.see("end")
        self.update_idletasks()

    def _tablo_filtrele(self, tree, query):
        query = query.lower()
        # Önce tüm satırları gizle/sil
        for item in tree.get_children():
            tree.delete(item)
        
        # Orijinal verileri sakladığın listeden (aşağıda anlatılan) tekrar doldur
        source_data = self.all_firma_data if tree == self.tree_firma else self.all_ogrenci_data
        
        for row in source_data:
            # Satırdaki herhangi bir sütun aramaya uyuyorsa ekle
            if any(query in str(cell).lower() for cell in row):
                tree.insert("", "end", values=row)

    # calistir fonksiyonunun en başında veri saklama listelerini tanımla
       

    def calistir(self):
        self.all_firma_data = []
        self.all_ogrenci_data = []
        try:
            fs = int(self.entries["Firma Sayısı"].get())
            os_val = int(self.entries["Öğrenci Sayısı"].get())
            seed = int(self.entries["Seed:"].get())
            ro = float(self.entries["Red Oranı:"].get())
            if not (30 <= fs <= 50):
                messagebox.showwarning("Girdi Hatası", "Firma sayısı 30 ile 50 arasında olmalıdır!")
                return
            
            if not (100 <= os_val <= 150):
                messagebox.showwarning("Girdi Hatası", "Öğrenci sayısı 100 ile 150 arasında olmalıdır!")
                return
            
            if not self.csv_path or not self.json_path:
                messagebox.showwarning("Uyarı", "Lütfen dosyaları seçin!"); return

            self.txt_log.delete("1.0", "end")
            self.tree_firma.delete(*self.tree_firma.get_children())
            self.tree_res.delete(*self.tree_res.get_children())

            def log_yaz(m, tag=None):
                self.txt_log.insert("end", m, tag)
                self.update_idletasks()

            secim = self.combo.get()
            final_ogr, final_fir = None, None

            if secim in ["Greedy", "İkisini Karşılaştır"]:
                o1, f1 = veri_uret(fs, os_val, seed, self.csv_path, self.json_path)
                r1 = simulasyon_motoru("greedy", o1, f1, ro, log_yaz)
                self._update_comp("greedy", r1)
                final_ogr, final_fir = o1, f1

            if secim in ["Heuristik", "İkisini Karşılaştır"]:
                if secim == "İkisini Karşılaştır": log_yaz("\n" + "="*60 + "\nHEURİSTİK ANALİZ BAŞLIYOR\n" + "="*60 + "\n", "tur")
                o2, f2 = veri_uret(fs, os_val, seed, self.csv_path, self.json_path)
                r2 = simulasyon_motoru(
    "heuristik",
    o2,
    f2,
    ro,
    log_yaz,
    swap_log=self.swap_gui_yaz
)

                self._update_comp("heuristik", r2)
                final_ogr, final_fir = o2, f2

            # SONUÇLARI TABLOLARA DOLDURMA (GÜNCELLENEN KISIM)
            # Tablo doldurma kısmını temizle
            for f_idx, f in final_fir.iterrows():
                y_isimler = final_ogr[final_ogr["atanan_firma"] == f_idx]["ad"].tolist()
                y_liste_str = "\n".join(y_isimler) if y_isimler else "-"
                satir = (f["ad"], f["gno_sarti"], f["kapasite"], f["kalan"], y_liste_str)
                self.all_firma_data.append(satir) 
                self.tree_firma.insert("", "end", values=satir) # Sadece bir kere insert!

            for _, o in final_ogr.iterrows():
                f_ad = final_fir.at[o["atanan_firma"], "ad"] if o["atanan_firma"] != -1 else "Açıkta"
                satir = (o["ad"], o["gno"], o["yerlesme_turu"], f_ad, memnuniyet_puani(o))
                self.all_ogrenci_data.append(satir)
                self.tree_res.insert("", "end", values=satir) # Sadece bir kere insert!

            self.son_ogrenciler = final_ogr
            self.son_firmalar = final_fir

            self.tabs.select(self.tab_log)
        except Exception as e:
            messagebox.showerror("Hata", f"Beklenmedik bir hata oluştu: {str(e)}")

if __name__ == "__main__":
    app = BTU_App()
    app.mainloop()