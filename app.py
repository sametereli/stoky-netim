from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash 
import sqlite3
import datetime
import os 
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# Flask uygulamasını oluştur
app = Flask(__name__, 
            static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'),
            static_url_path='/static')

# Oturum güvenliği için gizli bir anahtar. ÇOK ÖNEMLİ!
# Üretimde bu anahtarı güvenli bir yerden alın (örn. çevre değişkeni)
# Bu değeri rastgele ve uzun bir string ile DEĞİŞTİRMEYİ UNUTMAYIN!
app.config['SECRET_KEY'] = 'buraya_kendi_cok_gizli_ve_rastgele_anahtarinizi_yazin_lütfen_degistirin_burayi_secure' 

# Jinja2 şablonlarında Python'ın datetime.datetime.now() fonksiyonunu kullanabilmek için
app.jinja_env.globals.update(now=datetime.datetime.now)

# Yeni Jinja2 filtresi: Sayıları TL formatına dönüştürür (örn. 1234.56 -> 1.234,56 TL)
def format_tl(value):
    if value is None:
        return "0,00 TL"
    try:
        formatted_value = "{:,.2f}".format(float(value))
        return formatted_value.replace(",", "X").replace(".", ",").replace("X", ".") + " TL" 
    except (ValueError, TypeError):
        return str(value) + " TL" 

app.jinja_env.filters['format_tl'] = format_tl 

# Veritabanı bağlantısı için yardımcı fonksiyon
def get_db_connection():
    conn = sqlite3.connect('stok.db')
    conn.row_factory = sqlite3.Row 
    return conn

# Veritabanını başlatma fonksiyonu
def init_db():
    conn = get_db_connection()
    
    # urunler tablosu
    conn.execute('''
        CREATE TABLE IF NOT EXISTS urunler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad TEXT NOT NULL,
            stok INTEGER NOT NULL,
            alis_fiyat REAL NOT NULL,
            satis_fiyat REAL NOT NULL,
            birim TEXT NOT NULL,
            kategori TEXT NOT NULL
        );
    ''')
    
    # musteriler tablosu - ekleyen_kullanici_id sütunu eklendi
    conn.execute('''
        CREATE TABLE IF NOT EXISTS musteriler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_soyad TEXT NOT NULL,
            telefon TEXT,
            adres TEXT,
            eposta TEXT,
            ekleyen_kullanici_id INTEGER,
            FOREIGN KEY (ekleyen_kullanici_id) REFERENCES kullanicilar (id)
        );
    ''')

    # satislar tablosu (Ana satış işlemi kaydı)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS satislar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            musteri_id INTEGER NOT NULL,
            satis_tarihi TEXT NOT NULL,
            toplam_urun_fiyati REAL NOT NULL,
            iscilik_fiyati REAL DEFAULT 0.0,
            ek_notlar TEXT,
            FOREIGN KEY (musteri_id) REFERENCES musteriler (id)
        );
    ''')

    # satis_detaylari tablosu (Her bir satış işlemindeki satılan ürünlerin detayları)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS satis_detaylari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            satis_id INTEGER NOT NULL,
            urun_id INTEGER NOT NULL,
            satilan_adet INTEGER NOT NULL,
            birim_satis_fiyati REAL NOT NULL,
            FOREIGN KEY (satis_id) REFERENCES satislar (id),
            FOREIGN KEY (urun_id) REFERENCES urunler (id)
        );
    ''')

    # Ayarlar tablosu
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ayarlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sirket_adi TEXT,
            adres TEXT,
            telefon TEXT,
            eposta TEXT,
            düsuk_stok_esigi INTEGER DEFAULT 10 
        );
    ''')
    
    # Kullanicilar tablosu (Kullanıcı Yönetimi için)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_adi TEXT NOT NULL UNIQUE,
            parola_hash TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'personel' 
        );
    ''')

    # Malzeme İstemleri tablosu
    conn.execute('''
        CREATE TABLE IF NOT EXISTS malzeme_istemleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            urun_id INTEGER NOT NULL,
            talep_eden_kullanici_id INTEGER NOT NULL,
            talep_edilen_adet INTEGER NOT NULL,
            talep_tarihi TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'Beklemede', 
            onaylayan_kullanici_id INTEGER,
            onay_red_tarihi TEXT,
            aciklama TEXT,
            FOREIGN KEY (urun_id) REFERENCES urunler (id),
            FOREIGN KEY (talep_eden_kullanici_id) REFERENCES kullanicilar (id),
            FOREIGN KEY (onaylayan_kullanici_id) REFERENCES kullanicilar (id)
        );
    ''')


    # Varsayılan ayarları ekle
    conn.execute("INSERT OR IGNORE INTO ayarlar (id, sirket_adi, adres, telefon, eposta, düsuk_stok_esigi) VALUES (1, 'Şirket Adınız', 'Şirket Adresi', '0 (XXX) XXX XX XX', 'info@sirketiniz.com', 10);")

    # Örnek yönetici kullanıcısı ekle (sadece bir kez, eğer yoksa)
    if not conn.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = 'admin'").fetchone():
        hashed_password = generate_password_hash('adminpass', method='pbkdf2:sha256')
        conn.execute("INSERT INTO kullanicilar (kullanici_adi, parola_hash, rol) VALUES (?, ?, ?)",
                     ('admin', hashed_password, 'admin'))
        print("Varsayılan 'admin' kullanıcısı eklendi (Parola: adminpass)")

    # Örnek personel kullanıcısı ekle (sadece bir kez, eğer yoksa)
    if not conn.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = 'personel'").fetchone():
        hashed_password = generate_password_hash('personelpass', method='pbkdf2:sha256')
        conn.execute("INSERT INTO kullanicilar (kullanici_adi, parola_hash, rol) VALUES (?, ?, ?)",
                     ('personel', hashed_password, 'personel'))
        print("Varsayılan 'personel' kullanıcısı eklendi (Parola: personelpass)")


    # Örnek veriler (urunler için)
    conn.execute("INSERT OR IGNORE INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (1, '3*2,5 nym kablo', 50, 15.00, 20.00, 'metre', 'Kablolar');")
    conn.execute("INSERT OR IGNORE INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (2, 'Sıva altı priz', 75, 20.00, 28.00, 'adet', 'Prizler');")
    conn.execute("INSERT OR IGNORE INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (3, 'Monitör', 30, 1200.00, 1500.00, 'adet', 'Elektronik');")
    conn.execute("INSERT OR IGNORE INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (4, 'Web Kamerası', 20, 300.00, 400.00, 'adet', 'Elektronik');")
    conn.execute("INSERT OR IGNORE INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (5, '16 A sigorta', 36, 12.50, 17.00, 'adet', 'Sigortalar');")
    
    # Örnek müşteri verisi (ekleyen_kullanici_id eklendi)
    conn.execute("INSERT OR IGNORE INTO musteriler (id, ad_soyad, telefon, adres, eposta, ekleyen_kullanici_id) VALUES (1, 'Ali Yılmaz', '5551234567', 'Örnek Mah. No:1 İstanbul', 'ali@example.com', 1);") # Admin ekledi varsayalım
    conn.execute("INSERT OR IGNORE INTO musteriler (id, ad_soyad, telefon, adres, eposta, ekleyen_kullanici_id) VALUES (2, 'Ayşe Demir', '5559876543', 'Deneme Sok. No:5 Ankara', 'ayse@example.com', 2);") # Personel ekledi varsayalım

    conn.commit()
    conn.close()

# Uygulama başladığında veritabanını başlat
with app.app_context():
    init_db()

# --- Yetkilendirme için Yardımcı Fonksiyonlar/Dekoratörler ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'kullanici_id' not in session:
            flash('Bu sayfaya erişmek için giriş yapmalısınız.', 'danger')
            return redirect(url_for('giris'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'kullanici_id' not in session:
                flash('Bu sayfaya erişmek için giriş yapmalısınız.', 'danger')
                return redirect(url_for('giris'))
            
            conn = get_db_connection()
            user = conn.execute('SELECT rol FROM kullanicilar WHERE id = ?', (session['kullanici_id'],)).fetchone()
            conn.close()
            
            if user and user['rol'] == required_role:
                return f(*args, **kwargs)
            else:
                flash(f'Bu sayfaya erişim yetkiniz yok. Gerekli rol: {required_role}', 'danger')
                return redirect(url_for('anasayfa'))
        return decorated_function
    return decorator

# --- Kullanıcı Kimlik Doğrulama Rotaları ---
@app.route('/kayit', methods=('GET', 'POST'))
def kayit():
    conn = get_db_connection()
    user_count = conn.execute('SELECT COUNT(*) FROM kullanicilar').fetchone()[0]
    conn.close()

    if user_count > 0 and (session.get('kullanici_id') is None or session.get('rol') != 'admin'):
        flash('Yeni kullanıcı oluşturmak için yönetici olmalısınız.', 'danger')
        if user_count == 0: 
            pass 
        else:
            flash('Yeni kullanıcı oluşturmak için yönetici olmalısınız.', 'danger')
            return redirect(url_for('anasayfa')) 

    if request.method == 'POST':
        kullanici_adi = request.form['kullanici_adi']
        parola = request.form['parola']
        parola_tekrar = request.form['parola_tekrar']
        
        if not kullanici_adi or not parola:
            flash('Kullanıcı adı ve parola boş bırakılamaz!', 'danger')
            return redirect(url_for('kayit'))
        
        if parola != parola_tekrar:
            flash('Parolalar eşleşmiyor!', 'danger')
            return redirect(url_for('kayit'))
        
        conn = get_db_connection()
        existing_user = conn.execute('SELECT id FROM kullanicilar WHERE kullanici_adi = ?', (kullanici_adi,)).fetchone()
        if existing_user:
            conn.close()
            flash('Bu kullanıcı adı zaten mevcut!', 'danger')
            return redirect(url_for('kayit'))
        
        hashed_password = generate_password_hash(parola, method='pbkdf2:sha256')
        
        if user_count == 0:
            rol = 'admin'
            flash('Sistemin ilk kullanıcısı (YÖNETİCİ) başarıyla oluşturuldu! Şimdi giriş yapabilirsiniz.', 'success')
        else:
            rol = 'personel' 
            flash('Yeni personel hesabı başarıyla oluşturuldu!', 'success')

        conn.execute('INSERT INTO kullanicilar (kullanici_adi, parola_hash, rol) VALUES (?, ?, ?)',
                     (kullanici_adi, hashed_password, rol))
        conn.commit()
        conn.close()
        return redirect(url_for('giris'))
        
    return render_template('kayit.html')


@app.route('/giris', methods=('GET', 'POST'))
def giris():
    if 'kullanici_id' in session: 
        return redirect(url_for('anasayfa'))

    conn = get_db_connection()
    user_count = conn.execute('SELECT COUNT(*) FROM kullanicilar').fetchone()[0]
    conn.close()
    
    if user_count == 0:
        flash('Sistemde hiç kullanıcı yok. Lütfen ilk kullanıcıyı (yönetici) oluşturun.', 'info')
        return redirect(url_for('kayit'))

    if request.method == 'POST':
        kullanici_adi = request.form['kullanici_adi']
        parola = request.form['parola']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM kullanicilar WHERE kullanici_adi = ?', (kullanici_adi,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['parola_hash'], parola):
            session['kullanici_id'] = user['id']
            session['kullanici_adi'] = user['kullanici_adi']
            session['rol'] = user['rol']
            flash(f'Hoş geldiniz, {user["kullanici_adi"]}!', 'success')
            return redirect(url_for('anasayfa'))
        else:
            flash('Geçersiz kullanıcı adı veya parola.', 'danger')
            return redirect(url_for('giris'))
            
    return render_template('giris.html')

@app.route('/cikis')
@login_required 
def cikis():
    session.pop('kullanici_id', None)
    session.pop('kullanici_adi', None)
    session.pop('rol', None)
    flash('Başarıyla çıkış yaptınız.', 'info')
    return redirect(url_for('giris'))

# --- Admin Paneli Rotaları (Sadece Admin Erişebilir) ---
@app.route('/admin_panel/kullanicilar')
@role_required('admin')
def admin_panel_kullanicilar():
    conn = get_db_connection()
    kullanicilar = conn.execute('SELECT id, kullanici_adi, rol FROM kullanicilar ORDER BY kullanici_adi').fetchall()
    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()
    return render_template('admin_panel_kullanicilar.html', kullanicilar=kullanicilar, kategoriler=kategoriler)

@app.route('/admin_panel/kullanici_duzenle/<int:id>', methods=('GET', 'POST'))
@role_required('admin')
def admin_panel_kullanici_duzenle(id):
    conn = get_db_connection()
    kullanici = conn.execute('SELECT id, kullanici_adi, rol FROM kullanicilar WHERE id = ?', (id,)).fetchone()
    
    if kullanici is None:
        conn.close()
        flash('Kullanıcı bulunamadı!', 'danger')
        return redirect(url_for('admin_panel_kullanicilar'))

    if request.method == 'POST':
        yeni_rol = request.form['rol']
        
        if kullanici['id'] == session['kullanici_id']: 
            flash('Kendi rolünüzü değiştiremezsiniz!', 'danger')
            return redirect(url_for('admin_panel_kullanici_duzenle', id=id))
        
        conn.execute('UPDATE kullanicilar SET rol = ? WHERE id = ?', (yeni_rol, id))
        conn.commit()
        conn.close()
        flash('Kullanıcı rolü başarıyla güncellendi!', 'success')
        return redirect(url_for('admin_panel_kullanicilar'))
    
    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()
    return render_template('admin_panel_kullanici_duzenle.html', kullanici=kullanici, kategoriler=kategoriler)


@app.route('/admin_panel/kullanici_sil/<int:id>', methods=('POST',))
@role_required('admin')
def admin_panel_kullanici_sil(id):
    conn = get_db_connection()
    
    if id == session['kullanici_id']: 
        conn.close()
        flash('Kendi hesabınızı silemezsiniz!', 'danger')
        return redirect(url_for('admin_panel_kullanicilar'))
    
    admin_count = conn.execute("SELECT COUNT(*) FROM kullanicilar WHERE rol = 'admin'").fetchone()[0]
    if admin_count == 1 and conn.execute("SELECT rol FROM kullanicilar WHERE id = ?", (id,)).fetchone()['rol'] == 'admin':
        conn.close()
        flash('Sistemde son kalan yöneticiyi silemezsiniz!', 'danger')
        return redirect(url_for('admin_panel_kullanicilar'))

    conn.execute('DELETE FROM kullanicilar WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Kullanıcı başarıyla silindi!', 'info')
    return redirect(url_for('admin_panel_kullanicilar'))


# --- Malzeme İstemi Rotaları ---
@app.route('/malzeme_istem/olustur', methods=('GET', 'POST'))
@login_required 
@role_required('personel') # Sadece personeller istem oluşturabilir (Adminler bu rotaya erişemez)
def malzeme_istem_olustur():
    conn = get_db_connection()
    urunler = conn.execute('SELECT id, ad, stok, birim FROM urunler ORDER BY ad').fetchall()
    # urunler verilerini şablona göndermeden önce sözlüğe çeviriyoruz
    urunler_for_template = []
    for urun_row in urunler:
        urunler_for_template.append(dict(urun_row))

    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() # Navbar için
    conn.close()

    if request.method == 'POST':
        # Birden fazla ürün istemi için form verilerini al
        urun_ids = request.form.getlist('urun_id[]')
        talep_edilen_adetler = request.form.getlist('talep_edilen_adet[]')
        aciklama = request.form['aciklama'] # Tek bir açıklama tüm istem için
        
        if not urun_ids or not talep_edilen_adetler:
            flash('Lütfen en az bir ürün talep edin ve adetleri boş bırakmayın!', 'danger')
            return render_template('malzeme_istem_olustur.html', urunler=urunler_for_template, kategoriler=kategoriler)

        conn = get_db_connection()
        talep_tarihi = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        all_requests_valid = True
        
        for i in range(len(urun_ids)):
            urun_id = urun_ids[i]
            adet_str = talep_edilen_adetler[i]
            
            if not urun_id or not adet_str:
                flash('Tüm seçili ürünler için ürün ve adet boş bırakılamaz!', 'danger')
                all_requests_valid = False
                break

            try:
                talep_edilen_adet = int(adet_str)
                if talep_edilen_adet <= 0:
                    flash(f"Ürün ID {urun_id} için talep edilen adet pozitif bir sayı olmalıdır!", 'danger')
                    all_requests_valid = False
                    break
            except ValueError:
                flash(f"Ürün ID {urun_id} için talep edilen adet sayı olmalıdır!", 'danger')
                all_requests_valid = False
                break
            
            # Veritabanına kaydet
            conn.execute('INSERT INTO malzeme_istemleri (urun_id, talep_eden_kullanici_id, talep_edilen_adet, talep_tarihi, aciklama) VALUES (?, ?, ?, ?, ?)',
                         (urun_id, session['kullanici_id'], talep_edilen_adet, talep_tarihi, aciklama))
        
        if all_requests_valid:
            conn.commit()
            flash('Malzeme istem(ler)i başarıyla oluşturuldu ve beklemede!', 'success')
            conn.close()
            return redirect(url_for('malzeme_istem_listele'))
        else:
            conn.rollback() # Bir hata varsa tüm işlemleri geri al
            conn.close()
            # Hatalıysa tekrar formu göster, urunler_for_template'i tekrar gönder
            return render_template('malzeme_istem_olustur.html', urunler=urunler_for_template, kategoriler=kategoriler) 

    # GET isteği için veya POST hatası durumunda formu göster
    return render_template('malzeme_istem_olustur.html', urunler=urunler_for_template, kategoriler=kategoriler)


@app.route('/malzeme_istem/listele')
@login_required 
def malzeme_istem_listele():
    conn = get_db_connection()
    
    # Yönetici tüm istemleri görür, personel sadece kendi istemlerini görür
    if session.get('rol') == 'admin':
        istemler = conn.execute('''
            SELECT 
                mi.id, mi.talep_edilen_adet, mi.talep_tarihi, mi.durum, mi.aciklama,
                u.ad AS urun_ad, u.birim AS urun_birim, u.id AS urun_id,
                tk.kullanici_adi AS talep_eden_kullanici_adi,
                ok.kullanici_adi AS onaylayan_kullanici_adi
            FROM malzeme_istemleri mi
            JOIN urunler u ON mi.urun_id = u.id
            JOIN kullanicilar tk ON mi.talep_eden_kullanici_id = tk.id
            LEFT JOIN kullanicilar ok ON mi.onaylayan_kullanici_id = ok.id
            ORDER BY mi.talep_tarihi DESC
        ''').fetchall()
    else: # Personel sadece kendi istemlerini görür
        istemler = conn.execute('''
            SELECT 
                mi.id, mi.talep_edilen_adet, mi.talep_tarihi, mi.durum, mi.aciklama,
                u.ad AS urun_ad, u.birim AS urun_birim, u.id AS urun_id,
                tk.kullanici_adi AS talep_eden_kullanici_adi,
                ok.kullanici_adi AS onaylayan_kullanici_adi
            FROM malzeme_istemleri mi
            JOIN urunler u ON mi.urun_id = u.id
            JOIN kullanicilar tk ON mi.talep_eden_kullanici_id = tk.id
            LEFT JOIN kullanicilar ok ON mi.onaylayan_kullanici_id = ok.id
            WHERE mi.talep_eden_kullanici_id = ?
            ORDER BY mi.talep_tarihi DESC
        ''', (session['kullanici_id'],)).fetchall()

    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() # Navbar için
    conn.close()
    return render_template('malzeme_istem_listele.html', istemler=istemler, kategoriler=kategoriler)


@app.route('/malzeme_istem/onayla_reddet/<int:istem_id>', methods=['POST'])
@role_required('admin') 
def malzeme_istem_onayla_reddet(istem_id):
    action = request.form.get('action') 

    conn = get_db_connection()
    istem = conn.execute('SELECT * FROM malzeme_istemleri WHERE id = ?', (istem_id,)).fetchone()
    
    if istem is None:
        conn.close()
        flash('Malzeme istemi bulunamadı!', 'danger')
        return redirect(url_for('malzeme_istem_listele'))

    if istem['durum'] != 'Beklemede': 
        conn.close()
        flash('Bu istem zaten işlenmiş durumda.', 'warning')
        return redirect(url_for('malzeme_istem_listele'))

    if action == 'onayla':
        urun = conn.execute('SELECT stok, ad FROM urunler WHERE id = ?', (istem['urun_id'],)).fetchone()
        if urun['stok'] < istem['talep_edilen_adet']:
            conn.rollback()
            flash(f"'{urun['ad']}' için yeterli stok yok. İstek onaylanamadı.", 'danger')
            return redirect(url_for('malzeme_istem_listele'))
        
        conn.execute('UPDATE urunler SET stok = stok - ? WHERE id = ?', (istem['talep_edilen_adet'], istem['urun_id']))
        conn.execute('UPDATE malzeme_istemleri SET durum = ?, onaylayan_kullanici_id = ?, onay_red_tarihi = ? WHERE id = ?',
                     ('Onaylandı', session['kullanici_id'], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), istem_id))
        conn.commit()
        flash(f"Malzeme istemi (ID: {istem_id}) başarıyla onaylandı ve stoktan düşüldü.", 'success')
    elif action == 'reddet':
        conn.execute('UPDATE malzeme_istemleri SET durum = ?, onaylayan_kullanici_id = ?, onay_red_tarihi = ? WHERE id = ?',
                     ('Reddedildi', session['kullanici_id'], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), istem_id))
        conn.commit()
        flash(f"Malzeme istemi (ID: {istem_id}) reddedildi.", 'info')
    else:
        flash('Geçersiz işlem!', 'danger')

    conn.close()
    return redirect(url_for('malzeme_istem_listele'))


# --- Mevcut Rotalar (Yetkilendirme Eklendi) ---

@app.route('/test_resim') 
def test_resim():
    return app.send_static_file('images/satis.png')

@app.route('/')
@login_required 
def anasayfa():
    conn = get_db_connection()
    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()
    return render_template('anasayfa.html', kategoriler=kategoriler)

@app.route('/urun_listesi')
@login_required 
@role_required('admin') 
def urun_listesi():
    conn = get_db_connection()
    
    ayarlar = conn.execute('SELECT düsuk_stok_esigi FROM ayarlar WHERE id = 1').fetchone()
    düsuk_stok_esigi = ayarlar['düsuk_stok_esigi'] if ayarlar and ayarlar['düsuk_stok_esigi'] is not None else 10 

    kategori_filtre = request.args.get('kategori_filtre')
    search_term = request.args.get('search_term') 

    query = 'SELECT * FROM urunler'
    params = []
    conditions = []

    if kategori_filtre and kategori_filtre != "Tüm Kategoriler":
        conditions.append('kategori = ?')
        params.append(kategori_filtre)
    
    if search_term:
        conditions.append('ad LIKE ?') 
        params.append(f'%{search_term}%') 
    
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    
    query += ' ORDER BY ad' 

    urunler_raw = conn.execute(query, params).fetchall()
    
    urunler = []
    for urun_item in urunler_raw:
        urun_dict = dict(urun_item) 
        if urun_dict['stok'] <= düsuk_stok_esigi:
            urun_dict['is_düsuk_stok'] = True
        else:
            urun_dict['is_düsuk_stok'] = False
        urunler.append(urun_dict)


    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall()
    conn.close()
    
    return render_template('index.html', 
                           urunler=urunler, 
                           kategoriler=kategoriler, 
                           current_kategori=kategori_filtre,
                           current_search_term=search_term,
                           düsuk_stok_esigi=düsuk_stok_esigi) 

@app.route('/yeni_urun', methods=('GET', 'POST'))
@login_required
@role_required('admin') 
def yeni_urun():
    conn = get_db_connection()
    if request.method == 'POST':
        urun_adi = request.form['ad']
        stok_miktari = request.form['stok']
        alis_fiyat = request.form['alis_fiyat']
        satis_fiyat = request.form['satis_fiyat']
        birim = request.form['birim']
        kategori = request.form['kategori']
        yeni_kategori = request.form.get('yeni_kategori') 

        if kategori == 'Yeni Kategori Ekle' and yeni_kategori:
            kategori = yeni_kategori.strip()
        elif kategori == 'Yeni Kategori Ekle' and not yeni_kategori:
            conn.close()
            flash('Yeni kategori adı boş bırakılamaz!', 'danger')
            return redirect(url_for('yeni_urun'))

        if not urun_adi or not stok_miktari or not alis_fiyat or not satis_fiyat or not birim or not kategori:
            conn.close()
            flash('Tüm gerekli alanlar boş bırakılamaz!', 'danger')
            return redirect(url_for('yeni_urun'))
        
        try:
            stok_miktari = int(stok_miktari)
            alis_fiyat = float(alis_fiyat)
            satis_fiyat = float(satis_fiyat)
        except ValueError:
            conn.close()
            flash('Stok, alış/satış fiyatı sayı olmalıdır!', 'danger')
            return redirect(url_for('yeni_urun'))

        conn.execute('INSERT INTO urunler (ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (?, ?, ?, ?, ?, ?)',
                     (urun_adi, stok_miktari, alis_fiyat, satis_fiyat, birim, kategori))
        conn.commit()
        conn.close()
        flash('Ürün başarıyla eklendi!', 'success')
        return redirect(url_for('urun_listesi')) 

    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall()
    conn.close()
    return render_template('urun_ekle.html', kategoriler=kategoriler)

@app.route('/<int:id>/duzenle', methods=('GET', 'POST'))
@login_required
@role_required('admin') 
def duzenle(id):
    conn = get_db_connection()
    urun = conn.execute('SELECT * FROM urunler WHERE id = ?', (id,)).fetchone()

    if urun is None:
        conn.close()
        flash('Ürün bulunamadı!', 'danger')
        return redirect(url_for('urun_listesi'))

    if request.method == 'POST':
        urun_adi = request.form['ad']
        stok_miktari = request.form['stok']
        alis_fiyat = request.form['alis_fiyat']
        satis_fiyat = request.form['satis_fiyat']
        birim = request.form['birim']
        kategori = request.form['kategori']
        yeni_kategori = request.form.get('yeni_kategori') 

        if kategori == 'Yeni Kategori Ekle' and yeni_kategori:
            kategori = yeni_kategori.strip()
        elif kategori == 'Yeni Kategori Ekle' and not yeni_kategori:
            conn.close()
            flash('Yeni kategori adı boş bırakılamaz!', 'danger')
            return redirect(url_for('duzenle', id=id))

        if not urun_adi or not stok_miktari or not alis_fiyat or not satis_fiyat or not birim or not kategori:
            conn.close()
            flash('Tüm gerekli alanlar boş bırakılamaz!', 'danger')
            return redirect(url_for('duzenle', id=id))
        
        try:
            stok_miktari = int(stok_miktari)
            alis_fiyat = float(alis_fiyat)
            satis_fiyat = float(satis_fiyat)
        except ValueError:
            conn.close()
            flash('Stok, alış/satış fiyatı sayı olmalıdır!', 'danger')
            return redirect(url_for('duzenle', id=id))

        conn.execute('UPDATE urunler SET ad = ?, stok = ?, alis_fiyat = ?, satis_fiyat = ?, birim = ?, kategori = ? WHERE id = ?',
                     (urun_adi, stok_miktari, alis_fiyat, satis_fiyat, birim, kategori, id))
        conn.commit()
        conn.close()
        flash('Ürün başarıyla güncellendi!', 'success')
        return redirect(url_for('urun_listesi'))

    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall()
    conn.close()
    return render_template('urun_duzenle.html', urun=urun, kategoriler=kategoriler)

@app.route('/<int:id>/sil', methods=('POST',))
@login_required
@role_required('admin') 
def sil(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM urunler WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Ürün başarıyla silindi!', 'info')
    return redirect(url_for('urun_listesi'))

@app.route('/musteri_ekle', methods=('GET', 'POST'))
@login_required
@role_required('admin') # SADECE ADMINLER müşteri ekleyebilir
def musteri_ekle():
    conn = get_db_connection() 
    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()

    if request.method == 'POST':
        ad_soyad = request.form['ad_soyad']
        telefon = request.form['telefon']
        adres = request.form['adres']
        eposta = request.form['eposta']

        if not ad_soyad:
            flash('Müşteri Adı Soyadı boş bırakılamaz!', 'danger')
            return redirect(url_for('musteri_ekle'))

        conn = get_db_connection()
        conn.execute('INSERT INTO musteriler (ad_soyad, telefon, adres, eposta, ekleyen_kullanici_id) VALUES (?, ?, ?, ?, ?)',
                     (ad_soyad, telefon, adres, eposta, session['kullanici_id'])) # Ekleyen kullanıcı ID'si kaydedildi
        conn.commit()
        conn.close()
        flash('Müşteri başarıyla eklendi!', 'success')
        return redirect(url_for('satis_yap')) 

    return render_template('musteri_ekle.html', kategoriler=kategoriler)

@app.route('/musteri_duzenle/<int:id>', methods=('GET', 'POST'))
@login_required
@role_required('admin') # SADECE ADMINLER müşteri düzenleyebilir
def musteri_duzenle(id):
    conn = get_db_connection()
    musteri = conn.execute('SELECT * FROM musteriler WHERE id = ?', (id,)).fetchone()

    if musteri is None:
        conn.close()
        flash('Müşteri bulunamadı!', 'danger')
        return redirect(url_for('musteri_gecmisi'))

    if request.method == 'POST':
        ad_soyad = request.form['ad_soyad']
        telefon = request.form['telefon']
        adres = request.form['adres']
        eposta = request.form['eposta']

        if not ad_soyad:
            conn.close()
            flash('Müşteri Adı Soyadı boş bırakılamaz!', 'danger')
            return redirect(url_for('musteri_duzenle', id=id))

        conn.execute('UPDATE musteriler SET ad_soyad = ?, telefon = ?, adres = ?, eposta = ? WHERE id = ?',
                     (ad_soyad, telefon, adres, eposta, id))
        conn.commit()
        conn.close()
        flash('Müşteri başarıyla güncellendi!', 'success')
        return redirect(url_for('musteri_gecmisi')) 

    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()
    return render_template('musteri_duzenle.html', musteri=musteri, kategoriler=kategoriler)

@app.route('/ayarlar', methods=('GET', 'POST'))
@login_required
@role_required('admin') 
def ayarlar():
    conn = get_db_connection()
    sirket_bilgileri = conn.execute('SELECT * FROM ayarlar WHERE id = 1').fetchone()

    if request.method == 'POST':
        sirket_adi = request.form['sirket_adi']
        adres = request.form['adres']
        telefon = request.form['telefon']
        eposta = request.form['eposta']
        düsuk_stok_esigi = request.form['düsuk_stok_esigi'] 
        
        try:
            düsuk_stok_esigi = int(düsuk_stok_esigi)
            if düsuk_stok_esigi < 0:
                conn.close()
                flash('Düşük stok eşiği negatif olamaz!', 'danger')
                return redirect(url_for('ayarlar'))
        except ValueError:
            conn.close()
            flash('Düşük stok eşiği sayı olmalıdır!', 'danger')
            return redirect(url_for('ayarlar'))


        conn.execute('UPDATE ayarlar SET sirket_adi = ?, adres = ?, telefon = ?, eposta = ?, düsuk_stok_esigi = ? WHERE id = 1',
                     (sirket_adi, adres, telefon, eposta, düsuk_stok_esigi))
        conn.commit()
        conn.close()
        flash('Ayarlar başarıyla kaydedildi!', 'success')
        return redirect(url_for('ayarlar')) 
    
    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()
    return render_template('ayarlar.html', sirket_bilgileri=sirket_bilgileri, kategoriler=kategoriler)


@app.route('/satis_yap')
@login_required 
def satis_yap():
    conn = get_db_connection()
    urunler = conn.execute('SELECT * FROM urunler ORDER BY ad').fetchall()
    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall()
    musteriler = conn.execute('SELECT id, ad_soyad FROM musteriler ORDER BY ad_soyad').fetchall()
    conn.close()
    return render_template('satis_yap.html', urunler=urunler, kategoriler=kategoriler, musteriler=musteriler)

@app.route('/satis_onayla', methods=['POST'])
@login_required 
def satis_onayla():
    data = request.get_json() 
    
    if not data or not data.get('musteri_id'): 
        return jsonify({'success': False, 'message': 'Müşteri seçilmemiş veya geçersiz veri.'}), 400

    cart = data.get('cart', []) 
    musteri_id = data['musteri_id']
    iscilik_fiyati = float(data.get('iscilik_fiyati', 0.0))
    ek_notlar = data.get('ek_notlar', '')

    if not cart and iscilik_fiyati == 0:
        return jsonify({'success': False, 'message': 'Sepet boş ve işçilik fiyatı sıfır. Lütfen ürün ekleyin veya işçilik fiyatı girin.'}), 400

    conn = get_db_connection()
    try:
        # 1. Stok kontrolü yap ve toplam ürün fiyatını hesapla
        toplam_urun_fiyati = 0
        for item in cart:
            urun_id = item['id']
            satilan_adet = item['adet']
            
            urun = conn.execute('SELECT ad, stok, satis_fiyat FROM urunler WHERE id = ?', (urun_id,)).fetchone()
            if urun is None:
                conn.rollback() 
                return jsonify({'success': False, 'message': f"Ürün (ID: {urun_id}) bulunamadı."}), 404
            
            mevcut_stok = urun['stok']
            urun_ad = urun['ad']
            birim_satis_fiyati = urun['satis_fiyat'] 
            
            if satilan_adet > mevcut_stok:
                conn.rollback()
                return jsonify({'success': False, 'message': f"'{urun_ad}' için yeterli stok yok. Mevcut: {mevcut_stok}, İstenen: {satilan_adet}"}), 400
            
            toplam_urun_fiyati += birim_satis_fiyati * satilan_adet
        
        # 2. Satışı satislar tablosuna kaydet
        satis_tarihi = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute('INSERT INTO satislar (musteri_id, satis_tarihi, toplam_urun_fiyati, iscilik_fiyati, ek_notlar) VALUES (?, ?, ?, ?, ?)',
                              (musteri_id, satis_tarihi, toplam_urun_fiyati, iscilik_fiyati, ek_notlar))
        satis_id = cursor.lastrowid 

        # 3. Her bir ürün için satis_detaylari tablosuna kayıt ekle ve stoktan düş
        for item in cart:
            urun_id = item['id']
            satilan_adet = item['adet']
            birim_satis_fiyati_detay = conn.execute('SELECT satis_fiyat FROM urunler WHERE id = ?', (urun_id,)).fetchone()['satis_fiyat']

            conn.execute('INSERT INTO satis_detaylari (satis_id, urun_id, satilan_adet, birim_satis_fiyati) VALUES (?, ?, ?, ?)',
                         (satis_id, urun_id, satilan_adet, birim_satis_fiyati_detay))
            
            conn.execute('UPDATE urunler SET stok = stok - ? WHERE id = ?', (satilan_adet, urun_id))
        
        conn.commit() 
        return jsonify({'success': True, 'message': 'Satış başarıyla tamamlandı!', 'satis_id': satis_id}), 200

    except Exception as e:
        conn.rollback() 
        return jsonify({'success': False, 'message': f"Satış sırasında bir hata oluştu: {str(e)}"}), 500
    finally:
        conn.close()

@app.route('/musteri_gecmisi')
@login_required 
def musteri_gecmisi():
    conn = get_db_connection()
    # Müşteri Geçmişi rotası: Admin tüm müşterileri görür, Personel sadece kendi eklediği müşterileri görür
    if session.get('rol') == 'admin':
        musteriler = conn.execute('SELECT id, ad_soyad, telefon, eposta FROM musteriler ORDER BY ad_soyad').fetchall()
    else: # Personel sadece kendi eklediği müşterileri görür
        musteriler = conn.execute('SELECT id, ad_soyad, telefon, eposta FROM musteriler WHERE ekleyen_kullanici_id = ? ORDER BY ad_soyad', (session['kullanici_id'],)).fetchall()
        
    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()
    return render_template('musteri_gecmisi.html', musteriler=musteriler, kategoriler=kategoriler)

@app.route('/musteri_detay/<int:musteri_id>')
@login_required 
def musteri_detay(musteri_id):
    conn = get_db_connection()
    
    musteri = conn.execute('SELECT * FROM musteriler WHERE id = ?', (musteri_id,)).fetchone()
    if musteri is None:
        conn.close()
        flash('Müşteri bulunamadı!', 'danger')
        return redirect(url_for('musteri_gecmisi'))
    
    # Müşteri detayını sadece admin görebilir veya ekleyen kişi görebilir
    if session.get('rol') != 'admin' and musteri['ekleyen_kullanici_id'] != session['kullanici_id']:
        conn.close()
        flash('Bu müşterinin detaylarını görüntüleme yetkiniz yok!', 'danger')
        return redirect(url_for('musteri_gecmisi'))

    satislar = conn.execute('''
        SELECT 
            s.id AS satis_id,
            s.satis_tarihi,
            s.toplam_urun_fiyati,
            s.iscilik_fiyati,
            s.ek_notlar,
            sd.satilan_adet,
            sd.birim_satis_fiyati,
            u.ad AS urun_ad,
            u.birim AS urun_birim
        FROM satislar s
        LEFT JOIN satis_detaylari sd ON s.id = sd.satis_id 
        LEFT JOIN urunler u ON sd.urun_id = u.id
        WHERE s.musteri_id = ?
        ORDER BY s.satis_tarihi DESC, s.id DESC
    ''', (musteri_id,)).fetchall()

    gruplanmis_satislar = {}
    for satis in satislar:
        satis_id = satis['satis_id']
        if satis_id not in gruplanmis_satislar:
            gruplanmis_satislar[satis_id] = {
                'satis_id': satis['satis_id'],
                'satis_tarihi': satis['satis_tarihi'],
                'toplam_urun_fiyati': satis['toplam_urun_fiyati'], 
                'iscilik_fiyati': satis['iscilik_fiyati'],
                'ek_notlar': satis['ek_notlar'],
                'urunler': [] 
            }
        if satis['urun_ad']: # Sadece urun_ad varsa ürünleri ekle
            gruplanmis_satislar[satis_id]['urunler'].append({
                'urun_ad': satis['urun_ad'],
                'satilan_adet': satis['satilan_adet'],
                'birim_satis_fiyati': satis['birim_satis_fiyati'],
                'urun_birim': satis['urun_birim']
            })
    
    satis_listesi = sorted(list(gruplanmis_satislar.values()), key=lambda x: x['satis_tarihi'], reverse=True)

    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()
    return render_template('musteri_detay.html', musteri=musteri, satislar=satis_listesi, kategoriler=kategoriler)

@app.route('/fatura/<int:satis_id>')
@login_required 
def fatura(satis_id):
    conn = get_db_connection()
    
    satis = conn.execute('SELECT * FROM satislar WHERE id = ?', (satis_id,)).fetchone()
    if satis is None:
        conn.close()
        flash('Fatura bulunamadı!', 'danger')
        return redirect(url_for('anasayfa'))

    musteri = conn.execute('SELECT * FROM musteriler WHERE id = ?', (satis['musteri_id'],)).fetchone()
    if musteri is None:
        conn.close()
        flash('Müşteri bulunamadı!', 'danger')
        return redirect(url_for('anasayfa')) 

    urun_kalemleri = conn.execute('''
        SELECT 
            sd.satilan_adet,
            sd.birim_satis_fiyati,
            u.ad AS urun_ad,
            u.birim AS urun_birim
        FROM satis_detaylari sd
        JOIN urunler u ON sd.urun_id = u.id
        WHERE sd.satis_id = ?
    ''', (satis_id,)).fetchall()

    sirket_bilgileri = conn.execute('SELECT * FROM ayarlar WHERE id = 1').fetchone()
    if sirket_bilgileri is None:
        sirket_bilgileri = sqlite3.Row(None, ('Şirket Adı Yok', '', '', '')) 
    
    kategoriler = conn.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori').fetchall() 
    conn.close()

    toplam_urun_fiyati = satis['toplam_urun_fiyati']
    iscilik_fiyati = satis['iscilik_fiyati'] 
    genel_toplam = toplam_urun_fiyati + iscilik_fiyati

    return render_template('fatura.html', 
                           satis=satis, 
                           musteri=musteri, 
                           urun_kalemleri=urun_kalemleri, 
                           genel_toplam=genel_toplam,
                           sirket_bilgileri=sirket_bilgileri, 
                           kategoriler=kategoriler) 

# Uygulamayı çalıştır
if __name__ == '__main__':
    app.run(debug=True)