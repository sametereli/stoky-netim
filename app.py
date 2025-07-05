from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
# sqlite3 yerine PostgreSQL için psycopg2 ve os modülünü kullanacağız
import psycopg2
import psycopg2.extras # Sözlük olarak sonuç almak için
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
# Önceki hatanın çözüldüğünü varsayarak string formatını çift tırnakla güncellendi.
app.config['SECRET_KEY'] = "LÜTFEN_BURAYI_DEGISTIRIN_RASTGELE_BIR_DEGER_ATAYIN"

# Jinja2 şablonlarında Python'ın datetime.datetime.now() fonksiyonunu kullanabilmek için
app.jinja_env.globals.update(now=datetime.datetime.now)

# Yeni Jinja2 filtresi: Sayıları TL formatına dönüştürür (örn. 1234.56 -> 1.234,56 TL)
def format_tl(value):
    if value is None:
        return "0,00 TL"
    try:
        formatted_value = "{:,.2f}".format(float(value))
        # Türkiye formatına uygun virgül ve nokta dönüşümü
        return formatted_value.replace(",", "X").replace(".", ",").replace("X", ".") + " TL"
    except (ValueError, TypeError):
        return str(value) + " TL"

app.jinja_env.filters['format_tl'] = format_tl

# Veritabanı bağlantısı için yardımcı fonksiyon (PostgreSQL için güncellendi)
def get_db_connection():
    try:
        # DATABASE_URL Render ortam değişkenlerinden alınır
        DATABASE_URL = os.environ.get('DATABASE_URL')
        if not DATABASE_URL:
            # Yerel geliştirme için veya DATABASE_URL ayarlanmamışsa yedek
            # Kendi yerel PostgreSQL bağlantı bilginizi buraya yazabilirsiniz.
            # Örneğin: DATABASE_URL = "postgresql://kullanici:sifre@localhost:5432/veritabani_adi"
            raise ValueError("DATABASE_URL ortam değişkeni ayarlanmadı!")

        conn = psycopg2.connect(DATABASE_URL)
        # Sorgu sonuçlarını sözlük olarak almak için cursor_factory kullanılır
        return conn
    except Exception as e:
        print(f"Veritabanı bağlantı hatası: {e}")
        # Uygulamanın başlamaması durumunda detaylı hata logu için
        import traceback
        traceback.print_exc()
        raise # Hatayı yukarı fırlat, uygulamanın başlamasını engelle


# Veritabanını başlatma fonksiyonu (PostgreSQL ve örnek veri temizliği için güncellendi)
def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor() # SQL komutlarını çalıştırmak için cursor kullan

        # urunler tablosu
        cur.execute('''
            CREATE TABLE IF NOT EXISTS urunler (
                id SERIAL PRIMARY KEY,
                ad TEXT NOT NULL,
                stok INTEGER NOT NULL,
                alis_fiyat REAL NOT NULL,
                satis_fiyat REAL NOT NULL,
                birim TEXT NOT NULL,
                kategori TEXT NOT NULL
            );
        ''')

        # musteriler tablosu - ekleyen_kullanici_id sütunu eklendi
        cur.execute('''
            CREATE TABLE IF NOT EXISTS musteriler (
                id SERIAL PRIMARY KEY,
                ad_soyad TEXT NOT NULL,
                telefon TEXT,
                adres TEXT,
                eposta TEXT,
                ekleyen_kullanici_id INTEGER,
                FOREIGN KEY (ekleyen_kullanici_id) REFERENCES kullanicilar (id)
            );
        ''')

        # satislar tablosu (Ana satış işlemi kaydı)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS satislar (
                id SERIAL PRIMARY KEY,
                musteri_id INTEGER NOT NULL,
                satis_tarihi TEXT NOT NULL,
                toplam_urun_fiyati REAL NOT NULL,
                iscilik_fiyati REAL DEFAULT 0.0,
                ek_notlar TEXT,
                FOREIGN KEY (musteri_id) REFERENCES musteriler (id)
            );
        ''')

        # satis_detaylari tablosu (Her bir satış işlemindeki satılan ürünlerin detayları)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS satis_detaylari (
                id SERIAL PRIMARY KEY,
                satis_id INTEGER NOT NULL,
                urun_id INTEGER NOT NULL,
                satilan_adet INTEGER NOT NULL,
                birim_satis_fiyati REAL NOT NULL,
                FOREIGN KEY (satis_id) REFERENCES satislar (id),
                FOREIGN KEY (urun_id) REFERENCES urunler (id)
            );
        ''')

        # Ayarlar tablosu
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ayarlar (
                id SERIAL PRIMARY KEY,
                sirket_adi TEXT,
                adres TEXT,
                telefon TEXT,
                eposta TEXT,
                düsuk_stok_esigi INTEGER DEFAULT 10
            );
        ''')

        # Kullanicilar tablosu (Kullanıcı Yönetimi için)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS kullanicilar (
                id SERIAL PRIMARY KEY,
                kullanici_adi TEXT NOT NULL UNIQUE,
                parola_hash TEXT NOT NULL,
                rol TEXT NOT NULL DEFAULT 'personel'
            );
        ''')

        # Malzeme İstemleri tablosu
        cur.execute('''
            CREATE TABLE IF NOT EXISTS malzeme_istemleri (
                id SERIAL PRIMARY KEY,
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

        # Varsayılan ayarları ekle (Bu satırı tutabilirsiniz, çünkü ayarlarınız için bir başlangıç kaydı sağlar)
        cur.execute("INSERT INTO ayarlar (id, sirket_adi, adres, telefon, eposta, düsuk_stok_esigi) VALUES (1, 'Şirket Adınız', 'Şirket Adresi', '0 (XXX) XXX XX XX', 'info@sirketiniz.com', 10) ON CONFLICT (id) DO NOTHING;")

        # Örnek yönetici kullanıcısı ekle (sadece bir kez, eğer yoksa)
        cur.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = 'admin'")
        if not cur.fetchone():
            hashed_password = generate_password_hash('adminpass', method='pbkdf2:sha256')
            cur.execute("INSERT INTO kullanicilar (kullanici_adi, parola_hash, rol) VALUES (%s, %s, %s)",
                         ('admin', hashed_password, 'admin'))
            print("Varsayılan 'admin' kullanıcısı eklendi (Parola: adminpass)")

        # Örnek personel kullanıcısı ekle (sadece bir kez, eğer yoksa)
        cur.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = 'personel'")
        if not cur.fetchone():
            hashed_password = generate_password_hash('personelpass', method='pbkdf2:sha256')
            cur.execute("INSERT INTO kullanicilar (kullanici_adi, parola_hash, rol) VALUES (%s, %s, %s)",
                         ('personel', hashed_password, 'personel'))
            print("Varsayılan 'personel' kullanıcısı eklendi (Parola: personelpass)")


        # BURADAKİ TÜM ÖRNEK ÜRÜN VE MÜŞTERİ VERİ EKLEME SATIRLARI YORUM SATIRI YAPILDI VEYA SİLİNDİ
        # Bunlar artık uygulamanızın her başladığında veri tabanına yeniden eklenmeyecek.
        # Ürünlerinizi ve müşterilerinizi web arayüzünden eklemelisiniz.
        # cur.execute("INSERT INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (1, '3*2,5 nym kablo', 50, 15.00, 20.00, 'metre', 'Kablolar') ON CONFLICT (id) DO NOTHING;")
        # cur.execute("INSERT INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (2, 'Sıva altı priz', 75, 20.00, 28.00, 'adet', 'Prizler') ON CONFLICT (id) DO NOTHING;")
        # cur.execute("INSERT INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (3, 'Monitör', 30, 1200.00, 1500.00, 'adet', 'Elektronik') ON CONFLICT (id) DO NOTHING;")
        # cur.execute("INSERT INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (4, 'Web Kamerası', 20, 300.00, 400.00, 'adet', 'Elektronik') ON CONFLICT (id) DO NOTHING;")
        # cur.execute("INSERT INTO urunler (id, ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (5, '16 A sigorta', 36, 12.50, 17.00, 'adet', 'Sigortalar') ON CONFLICT (id) DO NOTHING;")

        # Örnek müşteri verisi yorum satırı yapıldı
        # cur.execute("INSERT INTO musteriler (id, ad_soyad, telefon, adres, eposta, ekleyen_kullanici_id) VALUES (1, 'Ali Yılmaz', '5551234567', 'Örnek Mah. No:1 İstanbul', 'ali@example.com', 1) ON CONFLICT (id) DO NOTHING;")
        # cur.execute("INSERT INTO musteriler (id, ad_soyad, telefon, adres, eposta, ekleyen_kullanici_id) VALUES (2, 'Ayşe Demir', '5559876543', 'Deneme Sok. No:5 Ankara', 'ayse@example.com', 2) ON CONFLICT (id) DO NOTHING;")

        conn.commit()
    except Exception as e:
        print(f"init_db sırasında hata oluştu: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback() # Hata durumunda rollback yap
        raise # Hatayı yeniden fırlat, uygulamanın başlamasını engelle
    finally:
        if conn:
            conn.close()

# Uygulama başladığında veritabanını başlat
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"Uygulama başlangıcında veritabanı başlatma hatası: {e}")
        # Bu hata uygulamanın başlatılmasını engelleyebilir, Render loglarında görünmeli.


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

            conn = None
            try:
                conn = get_db_connection()
                # PostgreSQL'de fetchone() döndürdüğü sonuç bir liste veya tuple olabilir.
                # Eğer RealDictCursor kullanıyorsanız zaten sözlük döner.
                # Varsayılan cursor ile erişmek için indeks kullanırız.
                # Buradaki select rol sorgusu için DictCursor kullanmadan da çalışır.
                user_row = conn.execute('SELECT rol FROM kullanicilar WHERE id = %s', (session['kullanici_id'],)).fetchone()
                user_role = user_row[0] if user_row else None # row[0] ile rol değerini al

                if user_role and user_role == required_role:
                    return f(*args, **kwargs)
                else:
                    flash(f'Bu sayfaya erişim yetkiniz yok. Gerekli rol: {required_role}', 'danger')
                    return redirect(url_for('anasayfa'))
            except Exception as e:
                print(f"Yetkilendirme sırasında hata: {e}")
                import traceback
                traceback.print_exc()
                flash('Yetkilendirme hatası oluştu.', 'danger')
                return redirect(url_for('anasayfa'))
            finally:
                if conn:
                    conn.close()
        return decorated_function
    return decorator

# --- Kullanıcı Kimlik Doğrulama Rotaları ---
@app.route('/kayit', methods=('GET', 'POST'))
def kayit():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM kullanicilar')
        user_count = cur.fetchone()[0]
        conn.close() # Bağlantıyı kapat

        if user_count > 0 and (session.get('kullanici_id') is None or session.get('rol') != 'admin'):
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
            cur = conn.cursor()
            cur.execute('SELECT id FROM kullanicilar WHERE kullanici_adi = %s', (kullanici_adi,))
            existing_user = cur.fetchone()
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

            cur.execute('INSERT INTO kullanicilar (kullanici_adi, parola_hash, rol) VALUES (%s, %s, %s)',
                         (kullanici_adi, hashed_password, rol))
            conn.commit()
            conn.close()
            return redirect(url_for('giris'))
    except Exception as e:
        print(f"Kayıt sırasında hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Kayıt sırasında bir hata oluştu.', 'danger')
        if conn: conn.rollback()
    finally:
        if conn: conn.close()
    return render_template('kayit.html')


@app.route('/giris', methods=('GET', 'POST'))
def giris():
    if 'kullanici_id' in session:
        return redirect(url_for('anasayfa'))

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM kullanicilar')
        user_count = cur.fetchone()[0]
        conn.close()

        if user_count == 0:
            flash('Sistemde hiç kullanıcı yok. Lütfen ilk kullanıcıyı (yönetici) oluşturun.', 'info')
            return redirect(url_for('kayit'))

        if request.method == 'POST':
            kullanici_adi = request.form['kullanici_adi']
            parola = request.form['parola']

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor kullan
            cur.execute('SELECT * FROM kullanicilar WHERE kullanici_adi = %s', (kullanici_adi,))
            user = cur.fetchone()
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
    except Exception as e:
        print(f"Giriş sırasında hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Giriş sırasında bir hata oluştu.', 'danger')
    finally:
        if conn: conn.close()
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
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT id, kullanici_adi, rol FROM kullanicilar ORDER BY kullanici_adi')
        kullanicilar = cur.fetchall()
        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('admin_panel_kullanicilar.html', kullanicilar=kullanicilar, kategoriler=kategoriler)
    except Exception as e:
        print(f"Admin panel kullanıcılar yüklenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Kullanıcı listesi yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('anasayfa'))
    finally:
        if conn: conn.close()

@app.route('/admin_panel/kullanici_duzenle/<int:id>', methods=('GET', 'POST'))
@role_required('admin')
def admin_panel_kullanici_duzenle(id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT id, kullanici_adi, rol FROM kullanicilar WHERE id = %s', (id,))
        kullanici = cur.fetchone()

        if kullanici is None:
            flash('Kullanıcı bulunamadı!', 'danger')
            return redirect(url_for('admin_panel_kullanicilar'))

        if request.method == 'POST':
            yeni_rol = request.form['rol']

            if kullanici['id'] == session['kullanici_id']:
                flash('Kendi rolünüzü değiştiremezsiniz!', 'danger')
                return redirect(url_for('admin_panel_kullanici_duzenle', id=id))

            cur.execute('UPDATE kullanicilar SET rol = %s WHERE id = %s', (yeni_rol, id))
            conn.commit()
            flash('Kullanıcı rolü başarıyla güncellendi!', 'success')
            return redirect(url_for('admin_panel_kullanicilar'))

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('admin_panel_kullanici_duzenle.html', kullanici=kullanici, kategoriler=kategoriler)
    except Exception as e:
        print(f"Kullanıcı düzenleme hatası: {e}")
        import traceback
        traceback.print_exc()
        flash('Kullanıcı düzenlenirken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('admin_panel_kullanicilar'))
    finally:
        if conn: conn.close()


@app.route('/admin_panel/kullanici_sil/<int:id>', methods=('POST',))
@role_required('admin')
def admin_panel_kullanici_sil(id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if id == session['kullanici_id']:
            flash('Kendi hesabınızı silemezsiniz!', 'danger')
            return redirect(url_for('admin_panel_kullanicilar'))

        cur.execute("SELECT COUNT(*) FROM kullanicilar WHERE rol = 'admin'")
        admin_count = cur.fetchone()[0]
        cur.execute("SELECT rol FROM kullanicilar WHERE id = %s", (id,))
        deleted_user_role = cur.fetchone()[0]

        if admin_count == 1 and deleted_user_role == 'admin':
            flash('Sistemde son kalan yöneticiyi silemezsiniz!', 'danger')
            return redirect(url_for('admin_panel_kullanicilar'))

        cur.execute('DELETE FROM kullanicilar WHERE id = %s', (id,))
        conn.commit()
        flash('Kullanıcı başarıyla silindi!', 'info')
        return redirect(url_for('admin_panel_kullanicilar'))
    except Exception as e:
        print(f"Kullanıcı silme hatası: {e}")
        import traceback
        traceback.print_exc()
        flash('Kullanıcı silinirken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('admin_panel_kullanicilar'))
    finally:
        if conn: conn.close()


# --- Malzeme İstemi Rotaları ---
@app.route('/malzeme_istem/olustur', methods=('GET', 'POST'))
@login_required
@role_required('personel') # Sadece personeller istem oluşturabilir (Adminler bu rotaya erişemez)
def malzeme_istem_olustur():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT id, ad, stok, birim FROM urunler ORDER BY ad')
        urunler_for_template = cur.fetchall()

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()

        if request.method == 'POST':
            urun_ids = request.form.getlist('urun_id[]')
            talep_edilen_adetler = request.form.getlist('talep_edilen_adet[]')
            aciklama = request.form['aciklama']

            if not urun_ids or not talep_edilen_adetler:
                flash('Lütfen en az bir ürün talep edin ve adetleri boş bırakmayın!', 'danger')
                return render_template('malzeme_istem_olustur.html', urunler=urunler_for_template, kategoriler=kategoriler)

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

                cur.execute('INSERT INTO malzeme_istemleri (urun_id, talep_eden_kullanici_id, talep_edilen_adet, talep_tarihi, aciklama) VALUES (%s, %s, %s, %s, %s)',
                             (urun_id, session['kullanici_id'], talep_edilen_adet, talep_tarihi, aciklama))

            if all_requests_valid:
                conn.commit()
                flash('Malzeme istem(ler)i başarıyla oluşturuldu ve beklemede!', 'success')
                return redirect(url_for('malzeme_istem_listele'))
            else:
                conn.rollback()
                return render_template('malzeme_istem_olustur.html', urunler=urunler_for_template, kategoriler=kategoriler)

        return render_template('malzeme_istem_olustur.html', urunler=urunler_for_template, kategoriler=kategoriler)
    except Exception as e:
        print(f"Malzeme istemi oluşturulurken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Malzeme istemi oluşturulurken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('anasayfa')) # Hata durumunda anasayfaya yönlendir
    finally:
        if conn: conn.close()


@app.route('/malzeme_istem/listele')
@login_required
def malzeme_istem_listele():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor

        if session.get('rol') == 'admin':
            cur.execute('''
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
            ''')
            istemler = cur.fetchall()
        else: # Personel sadece kendi istemlerini görür
            cur.execute('''
                SELECT
                    mi.id, mi.talep_edilen_adet, mi.talep_tarihi, mi.durum, mi.aciklama,
                    u.ad AS urun_ad, u.birim AS urun_birim, u.id AS urun_id,
                    tk.kullanici_adi AS talep_eden_kullanici_adi,
                    ok.kullanici_adi AS onaylayan_kullanici_adi
                FROM malzeme_istemleri mi
                JOIN urunler u ON mi.urun_id = u.id
                JOIN kullanicilar tk ON mi.talep_eden_kullanici_id = tk.id
                LEFT JOIN kullanicilar ok ON mi.onaylayan_kullanici_id = ok.id
                WHERE mi.talep_eden_kullanici_id = %s
                ORDER BY mi.talep_tarihi DESC
            ''', (session['kullanici_id'],))
            istemler = cur.fetchall()

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('malzeme_istem_listele.html', istemler=istemler, kategoriler=kategoriler)
    except Exception as e:
        print(f"Malzeme istemleri listelenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Malzeme istemleri yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('anasayfa'))
    finally:
        if conn: conn.close()


@app.route('/malzeme_istem/onayla_reddet/<int:istem_id>', methods=['POST'])
@role_required('admin')
def malzeme_istem_onayla_reddet(istem_id):
    action = request.form.get('action')

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT * FROM malzeme_istemleri WHERE id = %s', (istem_id,))
        istem = cur.fetchone()

        if istem is None:
            flash('Malzeme istemi bulunamadı!', 'danger')
            return redirect(url_for('malzeme_istem_listele'))

        if istem['durum'] != 'Beklemede':
            flash('Bu istem zaten işlenmiş durumda.', 'warning')
            return redirect(url_for('malzeme_istem_listele'))

        if action == 'onayla':
            cur.execute('SELECT stok, ad FROM urunler WHERE id = %s', (istem['urun_id'],))
            urun = cur.fetchone()
            if urun['stok'] < istem['talep_edilen_adet']:
                flash(f"'{urun['ad']}' için yeterli stok yok. İstek onaylanamadı.", 'danger')
                return redirect(url_for('malzeme_istem_listele'))

            cur.execute('UPDATE urunler SET stok = stok - %s WHERE id = %s', (istem['talep_edilen_adet'], istem['urun_id']))
            cur.execute('UPDATE malzeme_istemleri SET durum = %s, onaylayan_kullanici_id = %s, onay_red_tarihi = %s WHERE id = %s',
                         ('Onaylandı', session['kullanici_id'], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), istem_id))
            conn.commit()
            flash(f"Malzeme istemi (ID: {istem_id}) başarıyla onaylandı ve stoktan düşüldü.", 'success')
        elif action == 'reddet':
            cur.execute('UPDATE malzeme_istemleri SET durum = %s, onaylayan_kullanici_id = %s, onay_red_tarihi = %s WHERE id = %s',
                         ('Reddedildi', session['kullanici_id'], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), istem_id))
            conn.commit()
            flash(f"Malzeme istemi (ID: {istem_id}) reddedildi.", 'info')
        else:
            flash('Geçersiz işlem!', 'danger')

        return redirect(url_for('malzeme_istem_listele'))
    except Exception as e:
        print(f"Malzeme istemi onay/reddet sırasında hata: {e}")
        import traceback
        traceback.print_exc()
        flash('İşlem sırasında bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('malzeme_istem_listele'))
    finally:
        if conn: conn.close()


# --- Mevcut Rotalar (Yetkilendirme Eklendi) ---

@app.route('/test_resim')
def test_resim():
    return app.send_static_file('images/satis.png')

@app.route('/')
@login_required
def anasayfa():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('anasayfa.html', kategoriler=kategoriler)
    except Exception as e:
        print(f"Anasayfa yüklenirken hata: {e}")
        import traceback
        traceback.exc_info() # Hata detaylarını logla
        flash('Anasayfa yüklenirken bir hata oluştu.', 'danger')
        return "Anasayfa yüklenemedi", 500 # Uygulama çökmesini önlemek için
    finally:
        if conn: conn.close()

@app.route('/urun_listesi')
@login_required
@role_required('admin')
def urun_listesi():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor

        cur.execute('SELECT düsuk_stok_esigi FROM ayarlar WHERE id = 1')
        ayarlar = cur.fetchone()
        düsuk_stok_esigi = ayarlar['düsuk_stok_esigi'] if ayarlar and ayarlar['düsuk_stok_esigi'] is not None else 10

        kategori_filtre = request.args.get('kategori_filtre')
        search_term = request.args.get('search_term')

        query = 'SELECT * FROM urunler'
        params = []
        conditions = []

        if kategori_filtre and kategori_filtre != "Tüm Kategoriler":
            conditions.append('kategori = %s')
            params.append(kategori_filtre)

        if search_term:
            conditions.append('ad ILIKE %s') # ILIKE PostgreSQL'de case-insensitive arama için
            params.append(f'%{search_term}%')

        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        query += ' ORDER BY ad'

        cur.execute(query, params)
        urunler_raw = cur.fetchall()

        urunler = []
        for urun_item in urunler_raw:
            urun_dict = dict(urun_item) # RealDictCursor zaten sözlük döndürür, bu dönüşüm gereksiz ama zarar vermez
            if urun_dict['stok'] <= düsuk_stok_esigi:
                urun_dict['is_düsuk_stok'] = True
            else:
                urun_dict['is_düsuk_stok'] = False
            urunler.append(urun_dict)


        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('index.html',
                               urunler=urunler,
                               kategoriler=kategoriler,
                               current_kategori=kategori_filtre,
                               current_search_term=search_term,
                               düsuk_stok_esigi=düsuk_stok_esigi)
    except Exception as e:
        print(f"Ürün listesi yüklenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Ürün listesi yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('anasayfa'))
    finally:
        if conn: conn.close()

@app.route('/yeni_urun', methods=('GET', 'POST'))
@login_required
@role_required('admin')
def yeni_urun():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor

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
                flash('Yeni kategori adı boş bırakılamaz!', 'danger')
                return redirect(url_for('yeni_urun'))

            if not urun_adi or not stok_miktari or not alis_fiyat or not satis_fiyat or not birim or not kategori:
                flash('Tüm gerekli alanlar boş bırakılamaz!', 'danger')
                return redirect(url_for('yeni_urun'))

            try:
                stok_miktari = int(stok_miktari)
                alis_fiyat = float(alis_fiyat)
                satis_fiyat = float(satis_fiyat)
            except ValueError:
                flash('Stok, alış/satış fiyatı sayı olmalıdır!', 'danger')
                return redirect(url_for('yeni_urun'))

            cur.execute('INSERT INTO urunler (ad, stok, alis_fiyat, satis_fiyat, birim, kategori) VALUES (%s, %s, %s, %s, %s, %s)',
                         (urun_adi, stok_miktari, alis_fiyat, satis_fiyat, birim, kategori))
            conn.commit()
            flash('Ürün başarıyla eklendi!', 'success')
            return redirect(url_for('urun_listesi'))

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('urun_ekle.html', kategoriler=kategoriler)
    except Exception as e:
        print(f"Yeni ürün eklenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Yeni ürün eklenirken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('urun_listesi')) # Hata durumunda ürün listesine yönlendir
    finally:
        if conn: conn.close()

@app.route('/<int:id>/duzenle', methods=('GET', 'POST'))
@login_required
@role_required('admin')
def duzenle(id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT * FROM urunler WHERE id = %s', (id,))
        urun = cur.fetchone()

        if urun is None:
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
                flash('Yeni kategori adı boş bırakılamaz!', 'danger')
                return redirect(url_for('duzenle', id=id))

            if not urun_adi or not stok_miktari or not alis_fiyat or not satis_fiyat or not birim or not kategori:
                flash('Tüm gerekli alanlar boş bırakılamaz!', 'danger')
                return redirect(url_for('duzenle', id=id))

            try:
                stok_miktari = int(stok_miktari)
                alis_fiyat = float(alis_fiyat)
                satis_fiyat = float(satis_fiyat)
            except ValueError:
                flash('Stok, alış/satış fiyatı sayı olmalıdır!', 'danger')
                return redirect(url_for('duzenle', id=id))

            cur.execute('UPDATE urunler SET ad = %s, stok = %s, alis_fiyat = %s, satis_fiyat = %s, birim = %s, kategori = %s WHERE id = %s',
                         (urun_adi, stok_miktari, alis_fiyat, satis_fiyat, birim, kategori, id))
            conn.commit()
            flash('Ürün başarıyla güncellendi!', 'success')
            return redirect(url_for('urun_listesi'))

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('urun_duzenle.html', urun=urun, kategoriler=kategoriler)
    except Exception as e:
        print(f"Ürün düzenlenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Ürün düzenlenirken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('urun_listesi'))
    finally:
        if conn: conn.close()

@app.route('/<int:id>/sil', methods=('POST',))
@login_required
@role_required('admin')
def sil(id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM urunler WHERE id = %s', (id,))
        conn.commit()
        flash('Ürün başarıyla silindi!', 'info')
        return redirect(url_for('urun_listesi'))
    except Exception as e:
        print(f"Ürün silinirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Ürün silinirken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('urun_listesi'))
    finally:
        if conn: conn.close()

@app.route('/musteri_ekle', methods=('GET', 'POST'))
@login_required
@role_required('admin') # SADECE ADMINLER müşteri ekleyebilir
def musteri_ekle():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()

        if request.method == 'POST':
            ad_soyad = request.form['ad_soyad']
            telefon = request.form['telefon']
            adres = request.form['adres']
            eposta = request.form['eposta']

            if not ad_soyad:
                flash('Müşteri Adı Soyadı boş bırakılamaz!', 'danger')
                return redirect(url_for('musteri_ekle'))

            cur.execute('INSERT INTO musteriler (ad_soyad, telefon, adres, eposta, ekleyen_kullanici_id) VALUES (%s, %s, %s, %s, %s)',
                         (ad_soyad, telefon, adres, eposta, session['kullanici_id']))
            conn.commit()
            flash('Müşteri başarıyla eklendi!', 'success')
            return redirect(url_for('satis_yap'))

        return render_template('musteri_ekle.html', kategoriler=kategoriler)
    except Exception as e:
        print(f"Müşteri eklenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Müşteri eklenirken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('musteri_gecmisi'))
    finally:
        if conn: conn.close()

@app.route('/musteri_duzenle/<int:id>', methods=('GET', 'POST'))
@login_required
@role_required('admin') # SADECE ADMINLER müşteri düzenleyebilir
def musteri_duzenle(id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT * FROM musteriler WHERE id = %s', (id,))
        musteri = cur.fetchone()

        if musteri is None:
            flash('Müşteri bulunamadı!', 'danger')
            return redirect(url_for('musteri_gecmisi'))

        if request.method == 'POST':
            ad_soyad = request.form['ad_soyad']
            telefon = request.form['telefon']
            adres = request.form['adres']
            eposta = request.form['eposta']

            if not ad_soyad:
                flash('Müşteri Adı Soyadı boş bırakılamaz!', 'danger')
                return redirect(url_for('musteri_duzenle', id=id))

            cur.execute('UPDATE musteriler SET ad_soyad = %s, telefon = %s, adres = %s, eposta = %s WHERE id = %s',
                         (ad_soyad, telefon, adres, eposta, id))
            conn.commit()
            flash('Müşteri başarıyla güncellendi!', 'success')
            return redirect(url_for('musteri_gecmisi'))

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('musteri_duzenle.html', musteri=musteri, kategoriler=kategoriler)
    except Exception as e:
        print(f"Müşteri düzenlenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Müşteri düzenlenirken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('musteri_gecmisi'))
    finally:
        if conn: conn.close()

@app.route('/ayarlar', methods=('GET', 'POST'))
@login_required
@role_required('admin')
def ayarlar():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT * FROM ayarlar WHERE id = 1')
        sirket_bilgileri = cur.fetchone()

        if request.method == 'POST':
            sirket_adi = request.form['sirket_adi']
            adres = request.form['adres']
            telefon = request.form['telefon']
            eposta = request.form['eposta']
            düsuk_stok_esigi = request.form['düsuk_stok_esigi']

            try:
                düsuk_stok_esigi = int(düsuk_stok_esigi)
                if düsuk_stok_esigi < 0:
                    flash('Düşük stok eşiği negatif olamaz!', 'danger')
                    return redirect(url_for('ayarlar'))
            except ValueError:
                flash('Düşük stok eşiği sayı olmalıdır!', 'danger')
                return redirect(url_for('ayarlar'))

            cur.execute('UPDATE ayarlar SET sirket_adi = %s, adres = %s, telefon = %s, eposta = %s, düsuk_stok_esigi = %s WHERE id = 1',
                         (sirket_adi, adres, telefon, eposta, düsuk_stok_esigi))
            conn.commit()
            flash('Ayarlar başarıyla kaydedildi!', 'success')
            return redirect(url_for('ayarlar'))

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('ayarlar.html', sirket_bilgileri=sirket_bilgileri, kategoriler=kategoriler)
    except Exception as e:
        print(f"Ayarlar yüklenirken/kaydedilirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Ayarlar yüklenirken/kaydedilirken bir hata oluştu.', 'danger')
        if conn: conn.rollback()
        return redirect(url_for('anasayfa'))
    finally:
        if conn: conn.close()


@app.route('/satis_yap')
@login_required
def satis_yap():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        cur.execute('SELECT * FROM urunler ORDER BY ad')
        urunler = cur.fetchall()
        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        cur.execute('SELECT id, ad_soyad FROM musteriler ORDER BY ad_soyad')
        musteriler = cur.fetchall()
        return render_template('satis_yap.html', urunler=urunler, kategoriler=kategoriler, musteriler=musteriler)
    except Exception as e:
        print(f"Satış yap sayfası yüklenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Satış yap sayfası yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('anasayfa'))
    finally:
        if conn: conn.close()

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

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor

        # 1. Stok kontrolü yap ve toplam ürün fiyatını hesapla
        toplam_urun_fiyati = 0
        for item in cart:
            urun_id = item['id']
            satilan_adet = item['adet']

            cur.execute('SELECT ad, stok, satis_fiyat FROM urunler WHERE id = %s', (urun_id,))
            urun = cur.fetchone()
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
        cur.execute('INSERT INTO satislar (musteri_id, satis_tarihi, toplam_urun_fiyati, iscilik_fiyati, ek_notlar) VALUES (%s, %s, %s, %s, %s) RETURNING id',
                              (musteri_id, satis_tarihi, toplam_urun_fiyati, iscilik_fiyati, ek_notlar))
        satis_id = cur.fetchone()['id'] # RETURNING id ile son eklenen ID'yi al

        # 3. Her bir ürün için satis_detaylari tablosuna kayıt ekle ve stoktan düş
        for item in cart:
            urun_id = item['id']
            satilan_adet = item['adet']
            cur.execute('SELECT satis_fiyat FROM urunler WHERE id = %s', (urun_id,))
            birim_satis_fiyati_detay = cur.fetchone()['satis_fiyat']

            cur.execute('INSERT INTO satis_detaylari (satis_id, urun_id, satilan_adet, birim_satis_fiyati) VALUES (%s, %s, %s, %s)',
                         (satis_id, urun_id, satilan_adet, birim_satis_fiyati_detay))

            cur.execute('UPDATE urunler SET stok = stok - %s WHERE id = %s', (satilan_adet, urun_id))

        conn.commit()
        return jsonify({'success': True, 'message': 'Satış başarıyla tamamlandı!', 'satis_id': satis_id}), 200

    except Exception as e:
        print(f"Satış sırasında bir hata oluştu: {e}")
        import traceback
        traceback.print_exc()
        if conn: conn.rollback()
        return jsonify({'success': False, 'message': f"Satış sırasında bir hata oluştu: {str(e)}"}), 500
    finally:
        if conn: conn.close()

@app.route('/musteri_gecmisi')
@login_required
def musteri_gecmisi():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor
        # Müşteri Geçmişi rotası: Admin tüm müşterileri görür, Personel sadece kendi eklediği müşterileri görür
        if session.get('rol') == 'admin':
            cur.execute('SELECT id, ad_soyad, telefon, eposta FROM musteriler ORDER BY ad_soyad')
            musteriler = cur.fetchall()
        else: # Personel sadece kendi eklediği müşterileri görür
            cur.execute('SELECT id, ad_soyad, telefon, eposta FROM musteriler WHERE ekleyen_kullanici_id = %s ORDER BY ad_soyad', (session['kullanici_id'],))
            musteriler = cur.fetchall()

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('musteri_gecmisi.html', musteriler=musteriler, kategoriler=kategoriler)
    except Exception as e:
        print(f"Müşteri geçmişi yüklenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Müşteri geçmişi yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('anasayfa'))
    finally:
        if conn: conn.close()

@app.route('/musteri_detay/<int:musteri_id>')
@login_required
def musteri_detay(musteri_id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor

        cur.execute('SELECT * FROM musteriler WHERE id = %s', (musteri_id,))
        musteri = cur.fetchone()
        if musteri is None:
            flash('Müşteri bulunamadı!', 'danger')
            return redirect(url_for('musteri_gecmisi'))

        # Müşteri detayını sadece admin görebilir veya ekleyen kişi görebilir
        if session.get('rol') != 'admin' and musteri['ekleyen_kullanici_id'] != session['kullanici_id']:
            flash('Bu müşterinin detaylarını görüntüleme yetkiniz yok!', 'danger')
            return redirect(url_for('musteri_gecmisi'))

        cur.execute('''
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
            WHERE s.musteri_id = %s
            ORDER BY s.satis_tarihi DESC, s.id DESC
        ''', (musteri_id,))
        satislar_data = cur.fetchall() # RealDictCursor zaten sözlük listesi döndürür

        gruplanmis_satislar = {}
        for satis_item in satislar_data:
            satis_id = satis_item['satis_id']
            if satis_id not in gruplanmis_satislar:
                gruplanmis_satislar[satis_id] = {
                    'satis_id': satis_item['satis_id'],
                    'satis_tarihi': satis_item['satis_tarihi'],
                    'toplam_urun_fiyati': satis_item['toplam_urun_fiyati'],
                    'iscilik_fiyati': satis_item['iscilik_fiyati'],
                    'ek_notlar': satis_item['ek_notlar'],
                    'urunler': []
                }
            # urun_ad NULL gelirse (LEFT JOIN'den dolayı ürün yoksa) eklemiyoruz
            if satis_item['urun_ad']:
                gruplanmis_satislar[satis_id]['urunler'].append({
                    'urun_ad': satis_item['urun_ad'],
                    'satilan_adet': satis_item['satilan_adet'],
                    'birim_satis_fiyati': satis_item['birim_satis_fiyati'],
                    'urun_birim': satis_item['urun_birim']
                })

        satis_listesi = sorted(list(gruplanmis_satislar.values()), key=lambda x: x['satis_tarihi'], reverse=True)

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()
        return render_template('musteri_detay.html', musteri=musteri, satislar=satis_listesi, kategoriler=kategoriler)
    except Exception as e:
        print(f"Müşteri detayları yüklenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Müşteri detayları yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('musteri_gecmisi'))
    finally:
        if conn: conn.close()

@app.route('/fatura/<int:satis_id>')
@login_required
def fatura(satis_id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) # RealDictCursor

        cur.execute('SELECT * FROM satislar WHERE id = %s', (satis_id,))
        satis = cur.fetchone()
        if satis is None:
            flash('Fatura bulunamadı!', 'danger')
            return redirect(url_for('anasayfa'))

        cur.execute('SELECT * FROM musteriler WHERE id = %s', (satis['musteri_id'],))
        musteri = cur.fetchone()
        if musteri is None:
            flash('Müşteri bulunamadı!', 'danger')
            return redirect(url_for('anasayfa'))

        cur.execute('''
            SELECT
                sd.satilan_adet,
                sd.birim_satis_fiyati,
                u.ad AS urun_ad,
                u.birim AS urun_birim
            FROM satis_detaylari sd
            JOIN urunler u ON sd.urun_id = u.id
            WHERE sd.satis_id = %s
        ''', (satis_id,))
        urun_kalemleri = cur.fetchall()

        cur.execute('SELECT * FROM ayarlar WHERE id = 1')
        sirket_bilgileri = cur.fetchone()
        if sirket_bilgileri is None:
            sirket_bilgileri = {'sirket_adi': 'Şirket Adı Yok', 'adres': '', 'telefon': '', 'eposta': ''} # Sözlük olarak varsayılan değer

        cur.execute('SELECT DISTINCT kategori FROM urunler ORDER BY kategori')
        kategoriler = cur.fetchall()

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
    except Exception as e:
        print(f"Fatura yüklenirken hata: {e}")
        import traceback
        traceback.print_exc()
        flash('Fatura yüklenirken bir hata oluştu.', 'danger')
        return redirect(url_for('anasayfa'))
    finally:
        if conn: conn.close()

# Uygulamayı çalıştır
if __name__ == '__main__':
    # Üretim ortamında (Render gibi) Gunicorn veya başka bir WSGI sunucusu kullanılmalıdır.
    # Bu kısım sadece yerel geliştirme için kullanılır.
    app.run(debug=True)