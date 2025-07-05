from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash 
import os 
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_sqlalchemy import SQLAlchemy 
import datetime 

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
@app.template_filter('format_tl')
def format_tl_filter(value):
    if value is None:
        return "0,00 TL"
    try:
        formatted_value = "{:,.2f}".format(float(value))
        return formatted_value.replace(",", "X").replace(".", ",").replace("X", ".") + " TL" 
    except (ValueError, TypeError):
        return str(value) + " TL" 

# --- VERITABANI YAPILANDIRMASI (SQLAlchemy) ---
db_url = os.getenv("DATABASE_URL") or "sqlite:///stok.db" 

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

db = SQLAlchemy(app) 

# --- VERITABANI MODELLERİ (Tabloların Tanımları) ---
class Urun(db.Model):
    __tablename__ = 'urunler' 
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    stok = db.Column(db.Integer, default=0)
    alis_fiyat = db.Column(db.Float, nullable=False)
    satis_fiyat = db.Column(db.Float, nullable=False)
    birim = db.Column(db.String(50), nullable=False)
    kategori = db.Column(db.String(50), nullable=False)

class Kullanici(db.Model):
    __tablename__ = 'kullanicilar'
    id = db.Column(db.Integer, primary_key=True)
    kullanici_adi = db.Column(db.String(80), unique=True, nullable=False)
    parola_hash = db.Column(db.String(120), nullable=False)
    rol = db.Column(db.String(20), default='personel', nullable=False)

    musteriler = db.relationship('Musteri', backref='ekleyen_kullanici', lazy=True)
    talep_edilen_malzemeler = db.relationship('MalzemeIstemi', foreign_keys='MalzemeIstemi.talep_eden_kullanici_id', backref='talep_eden_kullanici', lazy=True)
    onaylanan_malzemeler = db.relationship('MalzemeIstemi', foreign_keys='MalzemeIstemi.onaylayan_kullanici_id', backref='onaylayan_kullanici', lazy=True)


class Musteri(db.Model):
    __tablename__ = 'musteriler'
    id = db.Column(db.Integer, primary_key=True)
    ad_soyad = db.Column(db.String(100), nullable=False)
    telefon = db.Column(db.String(20))
    adres = db.Column(db.String(200))
    eposta = db.Column(db.String(100))
    ekleyen_kullanici_id = db.Column(db.Integer, db.ForeignKey('kullanicilar.id'))

    satislar = db.relationship('Satis', backref='musteri', lazy=True)

class Satis(db.Model):
    __tablename__ = 'satislar'
    id = db.Column(db.Integer, primary_key=True)
    musteri_id = db.Column(db.Integer, db.ForeignKey('musteriler.id'), nullable=False)
    satis_tarihi = db.Column(db.String(50), nullable=False)
    toplam_urun_fiyati = db.Column(db.Float, nullable=False)
    iscilik_fiyati = db.Column(db.Float, default=0.0)
    ek_notlar = db.Column(db.Text)

    detaylar = db.relationship('SatisDetayi', backref='satis', lazy=True)

class SatisDetayi(db.Model):
    __tablename__ = 'satis_detaylari'
    id = db.Column(db.Integer, primary_key=True)
    satis_id = db.Column(db.Integer, db.ForeignKey('satislar.id'), nullable=False)
    urun_id = db.Column(db.Integer, db.ForeignKey('urunler.id'), nullable=False)
    satilan_adet = db.Column(db.Integer, nullable=False)
    birim_satis_fiyati = db.Column(db.Float, nullable=False)

    urun = db.relationship('Urun', backref='satis_detaylari', lazy=True)

class MalzemeIstemi(db.Model):
    __tablename__ = 'malzeme_istemleri'
    id = db.Column(db.Integer, primary_key=True)
    urun_id = db.Column(db.Integer, db.ForeignKey('urunler.id'), nullable=False)
    talep_eden_kullanici_id = db.Column(db.Integer, db.ForeignKey('kullanicilar.id'), nullable=False)
    talep_edilen_adet = db.Column(db.Integer, nullable=False)
    talep_tarihi = db.Column(db.String(50), nullable=False)
    durum = db.Column(db.String(20), default='Beklemede', nullable=False)
    onaylayan_kullanici_id = db.Column(db.Integer, db.ForeignKey('kullanicilar.id'), nullable=True)
    onay_red_tarihi = db.Column(db.String(50), nullable=True)
    aciklama = db.Column(db.Text)

    urun = db.relationship('Urun', backref='malzeme_istemleri', lazy=True)


class Ayar(db.Model):
    __tablename__ = 'ayarlar'
    id = db.Column(db.Integer, primary_key=True)
    sirket_adi = db.Column(db.String(100))
    adres = db.Column(db.String(200))
    telefon = db.Column(db.String(20))
    eposta = db.Column(db.String(100))
    düsuk_stok_esigi = db.Column(db.Integer, default=10)


# Uygulama başladığında veritabanı tablolarını oluştur ve varsayılan verileri ekle
# db.create_all() ve varsayılan veri ekleme işlemi buraya taşındı
with app.app_context():
    db.create_all() 
    
    if not Ayar.query.first():
        default_ayar = Ayar(sirket_adi='Şirket Adınız', adres='Şirket Adresi', telefon='0 (XXX) XXX XX XX', eposta='info@sirketiniz.com', düsuk_stok_esigi=10)
        db.session.add(default_ayar)
        db.session.commit()
        print("Varsayılan ayarlar eklendi.")

    if not Kullanici.query.filter_by(kullanici_adi='admin').first():
        hashed_password = generate_password_hash('adminpass', method='pbkdf2:sha256')
        admin_user = Kullanici(kullanici_adi='admin', parola_hash=hashed_password, rol='admin')
        db.session.add(admin_user)
        db.session.commit()
        print("Varsayılan 'admin' kullanıcısı eklendi (Parola: adminpass)")

    if not Kullanici.query.filter_by(kullanici_adi='personel').first():
        hashed_password = generate_password_hash('personelpass', method='pbkdf2:sha256')
        personel_user = Kullanici(kullanici_adi='personel', parola_hash=hashed_password, rol='personel')
        db.session.add(personel_user)
        db.session.commit()
        print("Varsayılan 'personel' kullanıcısı eklendi (Parola: personelpass)")

    if not Urun.query.first():
        db.session.add_all([
            Urun(ad='3*2,5 nym kablo', stok=50, alis_fiyat=15.00, satis_fiyat=20.00, birim='metre', kategori='Kablolar'),
            Urun(ad='Sıva altı priz', stok=75, alis_fiyat=20.00, satis_fiyat=28.00, birim='adet', kategori='Prizler'),
            Urun(ad='Monitör', stok=30, alis_fiyat=1200.00, satis_fiyat=1500.00, birim='adet', kategori='Elektronik'),
            Urun(ad='Web Kamerası', stok=20, alis_fiyat=300.00, satis_fiyat=400.00, birim='adet', kategori='Elektronik'),
            Urun(ad='16 A sigorta', stok=36, alis_fiyat=12.50, satis_fiyat=17.00, birim='adet', kategori='Sigortalar')
        ])
        db.session.commit()
        print("Örnek ürünler eklendi.")

    if not Musteri.query.first():
        admin_user = Kullanici.query.filter_by(kullanici_adi='admin').first()
        personel_user = Kullanici.query.filter_by(kullanici_adi='personel').first()

        admin_id = admin_user.id if admin_user else None
        personel_id = personel_user.id if personel_user else None

        if admin_id and personel_id: 
            db.session.add_all([
                Musteri(ad_soyad='Ali Yılmaz', telefon='5551234567', adres='Örnek Mah. No:1 İstanbul', eposta='ali@example.com', ekleyen_kullanici_id=admin_id),
                Musteri(ad_soyad='Ayşe Demir', telefon='5559876543', adres='Deneme Sok. No:5 Ankara', eposta='ayse@example.com', ekleyen_kullanici_id=personel_id)
            ])
            db.session.commit()
            print("Örnek müşteriler eklendi.")
        else:
            print("Örnek müşteriler eklenemedi: Varsayılan admin veya personel kullanıcısı bulunamadı.")


# Jinja2 filtresi: Sayıları TL formatına dönüştürür (örn. 1234.56 -> 1.234,56 TL)
@app.template_filter('format_tl')
def format_tl_filter(value):
    if value is None:
        return "0,00 TL"
    try:
        formatted_value = "{:,.2f}".format(float(value))
        return formatted_value.replace(",", "X").replace(".", ",").replace("X", ".") + " TL" 
    except (ValueError, TypeError):
        return str(value) + " TL" 

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
            
            user = Kullanici.query.get(session['kullanici_id'])
            
            if user and user.rol == required_role:
                return f(*args, **kwargs)
            else:
                flash(f'Bu sayfaya erişim yetkiniz yok. Gerekli rol: {required_role}', 'danger')
                return redirect(url_for('anasayfa'))
        return decorated_function
    return decorator

# --- Kullanıcı Kimlik Doğrulama Rotaları ---
@app.route('/kayit', methods=('GET', 'POST'))
def kayit():
    user_count = Kullanici.query.count()

    if user_count > 0 and (session.get('kullanici_id') is None or session.get('rol') != 'admin'):
        flash('Yeni kullanıcı oluşturmak için yönetici olmalısınız.', 'danger')
        if session.get('kullanici_id') is None: 
            return redirect(url_for('giris'))
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
        
        existing_user = Kullanici.query.filter_by(kullanici_adi=kullanici_adi).first()
        if existing_user:
            flash('Bu kullanıcı adı zaten mevcut!', 'danger')
            return redirect(url_for('kayit'))
        
        hashed_password = generate_password_hash(parola, method='pbkdf2:sha256')
        
        if user_count == 0:
            rol = 'admin'
            flash('Sistemin ilk kullanıcısı (YÖNETİCİ) başarıyla oluşturuldu! Şimdi giriş yapabilirsiniz.', 'success')
        else:
            rol = 'personel' 
            flash('Yeni personel hesabı başarıyla oluşturuldu!', 'success')

        new_user = Kullanici(kullanici_adi=kullanici_adi, parola_hash=hashed_password, rol=rol)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('giris'))
        
    return render_template('kayit.html')


@app.route('/giris', methods=('GET', 'POST'))
def giris():
    if 'kullanici_id' in session: 
        return redirect(url_for('anasayfa'))

    user_count = Kullanici.query.count()
    
    if user_count == 0:
        flash('Sistemde hiç kullanıcı yok. Lütfen ilk kullanıcıyı (yönetici) oluşturun.', 'info')
        return redirect(url_for('kayit'))

    if request.method == 'POST':
        kullanici_adi = request.form['kullanici_adi']
        parola = request.form['parola']
        
        user = Kullanici.query.filter_by(kullanici_adi=kullanici_adi).first()
        
        if user and check_password_hash(user.parola_hash, parola):
            session['kullanici_id'] = user.id
            session['kullanici_adi'] = user.kullanici_adi
            session['rol'] = user.rol
            flash(f'Hoş geldiniz, {user.kullanici_adi}!', 'success')
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
    kullanicilar = Kullanici.query.order_by(Kullanici.kullanici_adi).all()
    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('admin_panel_kullanicilar.html', kullanicilar=kullanicilar, kategoriler=kategoriler)

@app.route('/admin_panel/kullanici_duzenle/<int:id>', methods=('GET', 'POST'))
@role_required('admin')
def admin_panel_kullanici_duzenle(id):
    kullanici = Kullanici.query.get(id)
    
    if kullanici is None:
        flash('Kullanıcı bulunamadı!', 'danger')
        return redirect(url_for('admin_panel_kullanicilar'))

    if request.method == 'POST':
        yeni_rol = request.form['rol']
        
        if kullanici.id == session['kullanici_id']: 
            flash('Kendi rolünüzü değiştiremezsiniz!', 'danger')
            return redirect(url_for('admin_panel_kullanici_duzenle', id=id))
        
        kullanici.rol = yeni_rol
        db.session.commit()
        flash('Kullanıcı rolü başarıyla güncellendi!', 'success')
        return redirect(url_for('admin_panel_kullanicilar'))
    
    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('admin_panel_kullanici_duzenle.html', kullanici=kullanici, kategoriler=kategoriler)


@app.route('/admin_panel/kullanici_sil/<int:id>', methods=('POST',))
@role_required('admin')
def admin_panel_kullanici_sil(id):
    kullanici = Kullanici.query.get(id)
    
    if kullanici.id == session['kullanici_id']: 
        flash('Kendi hesabınızı silemezsiniz!', 'danger')
        return redirect(url_for('admin_panel_kullanicilar'))
    
    admin_count = Kullanici.query.filter_by(rol='admin').count()
    if admin_count == 1 and kullanici.rol == 'admin':
        flash('Sistemde son kalan yöneticiyi silemezsiniz!', 'danger')
        return redirect(url_for('admin_panel_kullanicilar'))

    db.session.delete(kullanici)
    db.session.commit()
    flash('Kullanıcı başarıyla silindi!', 'info')
    return redirect(url_for('admin_panel_kullanicilar'))


# --- Malzeme İstemi Rotaları ---
@app.route('/malzeme_istem/olustur', methods=('GET', 'POST'))
@login_required 
@role_required('personel') 
def malzeme_istem_olustur():
    urunler_raw = Urun.query.order_by(Urun.ad).all()
    urunler_for_template = []
    for urun_obj in urunler_raw:
        urun_dict = urun_obj.__dict__
        urun_dict.pop('_sa_instance_state', None) 
        urunler_for_template.append(urun_dict)

    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all() 

    if request.method == 'POST':
        urun_ids = request.form.getlist('urun_id[]')
        talep_edilen_adetler = request.form.getlist('talep_edilen_adet[]')
        aciklama = request.form['aciklama']
        
        if not urun_ids or not talep_edilen_adetler or len(urun_ids) == 0: 
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
            
            new_malzeme_istem = MalzemeIstemi(
                urun_id=urun_id, 
                talep_eden_kullanici_id=session['kullanici_id'], 
                talep_edilen_adet=talep_edilen_adet, 
                talep_tarihi=talep_tarihi, 
                aciklama=aciklama
            )
            db.session.add(new_malzeme_istem)
        
        if all_requests_valid:
            db.session.commit()
            flash('Malzeme istem(ler)i başarıyla oluşturuldu ve beklemede!', 'success')
            return redirect(url_for('malzeme_istem_listele'))
        else:
            db.session.rollback() 
            return render_template('malzeme_istem_olustur.html', urunler=urunler_for_template, kategoriler=kategoriler) 

    return render_template('malzeme_istem_olustur.html', urunler=urunler_for_template, kategoriler=kategoriler)


@app.route('/malzeme_istem/listele')
@login_required 
def malzeme_istem_listele():
    if session.get('rol') == 'admin':
        istemler = db.session.query(
            MalzemeIstemi,
            Urun.ad.label('urun_ad'), Urun.birim.label('urun_birim'), Urun.id.label('urun_id'),
            Kullanici.kullanici_adi.label('talep_eden_kullanici_adi'),
            db.case([(Kullanici.id == MalzemeIstemi.onaylayan_kullanici_id, Kullanici.kullanici_adi)], else_=None).label('onaylayan_kullanici_adi')
        ).join(Urun, MalzemeIstemi.urun_id == Urun.id)\
         .join(Kullanici, MalzemeIstemi.talep_eden_kullanici_id == Kullanici.id)\
         .outerjoin(Kullanici, MalzemeIstemi.onaylayan_kullanici_id == Kullanici.id)\
         .order_by(Kullanici.kullanici_adi.asc(), MalzemeIstemi.talep_tarihi.desc()).all()
        
        gruplanmis_istemler = {}
        for istem_obj, urun_ad, urun_birim, urun_id, talep_eden_kullanici_adi, onaylayan_kullanici_adi in istemler:
            istem_dict = istem_obj.__dict__
            istem_dict.pop('_sa_instance_state', None) 
            istem_dict['urun_ad'] = urun_ad
            istem_dict['urun_birim'] = urun_birim
            istem_dict['urun_id'] = urun_id
            istem_dict['talep_eden_kullanici_adi'] = talep_eden_kullanici_adi
            istem_dict['onaylayan_kullanici_adi'] = onaylayan_kullanici_adi
            
            if talep_eden_kullanici_adi not in gruplanmis_istemler:
                gruplanmis_istemler[talep_eden_kullanici_adi] = []
            gruplanmis_istemler[talep_eden_kullanici_adi].append(istem_dict)
        
    else: # Personel sadece kendi istemlerini görür
        istemler = db.session.query(
            MalzemeIstemi,
            Urun.ad.label('urun_ad'), Urun.birim.label('urun_birim'), Urun.id.label('urun_id'),
            Kullanici.kullanici_adi.label('talep_eden_kullanici_adi'),
            db.case([(Kullanici.id == MalzemeIstemi.onaylayan_kullanici_id, Kullanici.kullanici_adi)], else_=None).label('onaylayan_kullanici_adi')
        ).join(Urun, MalzemeIstemi.urun_id == Urun.id)\
         .join(Kullanici, MalzemeIstemi.talep_eden_kullanici_id == Kullanici.id)\
         .outerjoin(Kullanici, MalzemeIstemi.onaylayan_kullanici_id == Kullanici.id)\
         .filter(MalzemeIstemi.talep_eden_kullanici_id == session['kullanici_id'])\
         .order_by(MalzemeIstemi.talep_tarihi.desc()).all()
        
        gruplanmis_istemler = {'Kendi İstemlerim': []}
        for istem_obj, urun_ad, urun_birim, urun_id, talep_eden_kullanici_adi, onaylayan_kullanici_adi in istemler:
            istem_dict = istem_obj.__dict__
            istem_dict.pop('_sa_instance_state', None)
            istem_dict['urun_ad'] = urun_ad
            istem_dict['urun_birim'] = urun_birim
            istem_dict['urun_id'] = urun_id
            istem_dict['talep_eden_kullanici_adi'] = talep_eden_kullanici_adi
            istem_dict['onaylayan_kullanici_adi'] = onaylayan_kullanici_adi
            gruplanmis_istemler['Kendi İstemlerim'].append(istem_dict)

    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    
    return render_template('malzeme_istem_listele.html', 
                           gruplanmis_istemler=gruplanmis_istemler, 
                           kategoriler=kategoriler)


@app.route('/malzeme_istem/onayla_reddet/<int:istem_id>', methods=['POST'])
@role_required('admin') 
def malzeme_istem_onayla_reddet(istem_id):
    action = request.form.get('action') 

    istem = MalzemeIstemi.query.get(istem_id)
    
    if istem is None:
        flash('Malzeme istemi bulunamadı!', 'danger')
        return redirect(url_for('malzeme_istem_listele'))

    if istem.durum != 'Beklemede': 
        flash('Bu istem zaten işlenmiş durumda.', 'warning')
        return redirect(url_for('malzeme_istem_listele'))

    if action == 'onayla':
        urun = Urun.query.get(istem.urun_id)
        if urun.stok < istem.talep_edilen_adet:
            flash(f"'{urun.ad}' için yeterli stok yok. İstek onaylanamadı.", 'danger')
            return redirect(url_for('malzeme_istem_listele'))
        
        urun.stok -= istem.talep_edilen_adet
        istem.durum = 'Onaylandı'
        istem.onaylayan_kullanici_id = session['kullanici_id']
        istem.onay_red_tarihi = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.commit()
        flash(f"Malzeme istemi (ID: {istem_id}) başarıyla onaylandı ve stoktan düşüldü.", 'success')
    elif action == 'reddet':
        istem.durum = 'Reddedildi'
        istem.onaylayan_kullanici_id = session['kullanici_id']
        istem.onay_red_tarihi = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.commit()
        flash(f"Malzeme istemi (ID: {istem_id}) reddedildi.", 'info')
    else:
        flash('Geçersiz işlem!', 'danger')

    return redirect(url_for('malzeme_istem_listele'))


# --- Mevcut Rotalar (Yetkilendirme Eklendi) ---

@app.route('/test_resim') 
def test_resim():
    return app.send_static_file('images/satis.png')

@app.route('/')
@login_required 
def anasayfa():
    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('anasayfa.html', kategoriler=kategoriler)

@app.route('/urun_listesi')
@login_required 
@role_required('admin') 
def urun_listesi():
    ayarlar = Ayar.query.first()
    düsuk_stok_esigi = ayarlar.düsuk_stok_esigi if ayarlar and ayarlar.düsuk_stok_esigi is not None else 10 

    kategori_filtre = request.args.get('kategori_filtre')
    search_term = request.args.get('search_term') 

    query = Urun.query
    
    if kategori_filtre and kategori_filtre != "Tüm Kategoriler":
        query = query.filter_by(kategori=kategori_filtre)
    
    if search_term:
        query = query.filter(Urun.ad.like(f'%{search_term}%')) 
    
    urunler = query.order_by(Urun.ad).all()
    
    urunler_for_template = []
    for urun_item in urunler:
        urun_dict = urun_item.__dict__
        urun_dict.pop('_sa_instance_state', None) 
        if urun_dict['stok'] <= düsuk_stok_esigi:
            urun_dict['is_düsuk_stok'] = True
        else:
            urun_dict['is_düsuk_stok'] = False
        urunler_for_template.append(urun_dict)

    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    
    return render_template('index.html', 
                           urunler=urunler_for_template, 
                           kategoriler=kategoriler, 
                           current_kategori=kategori_filtre,
                           current_search_term=search_term,
                           düsuk_stok_esigi=düsuk_stok_esigi) 

@app.route('/yeni_urun', methods=('GET', 'POST'))
@login_required
@role_required('admin') 
def yeni_urun():
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

        new_urun = Urun(ad=urun_adi, stok=stok_miktari, alis_fiyat=alis_fiyat, satis_fiyat=satis_fiyat, birim=birim, kategori=kategori)
        db.session.add(new_urun)
        db.session.commit()
        flash('Ürün başarıyla eklendi!', 'success')
        return redirect(url_for('urun_listesi')) 

    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('urun_ekle.html', kategoriler=kategoriler)

@app.route('/<int:id>/duzenle', methods=('GET', 'POST'))
@login_required
@role_required('admin') 
def duzenle(id):
    urun = Urun.query.get(id)

    if urun is None:
        flash('Ürün bulunamadı!', 'danger')
        return redirect(url_for('urun_listesi'))

    if request.method == 'POST':
        urun.ad = request.form['ad']
        urun.stok = request.form['stok']
        urun.alis_fiyat = request.form['alis_fiyat']
        urun.satis_fiyat = request.form['satis_fiyat']
        urun.birim = request.form['birim']
        kategori = request.form['kategori']
        yeni_kategori = request.form.get('yeni_kategori') 

        if kategori == 'Yeni Kategori Ekle' and yeni_kategori:
            urun.kategori = yeni_kategori.strip()
        elif kategori == 'Yeni Kategori Ekle' and not yeni_kategori:
            flash('Yeni kategori adı boş bırakılamaz!', 'danger')
            return redirect(url_for('duzenle', id=id))

        if not urun.ad or not urun.stok or not urun.alis_fiyat or not urun.satis_fiyat or not urun.birim or not urun.kategori:
            flash('Tüm gerekli alanlar boş bırakılamaz!', 'danger')
            return redirect(url_for('duzenle', id=id))
        
        try:
            urun.stok = int(urun.stok)
            urun.alis_fiyat = float(urun.alis_fiyat)
            urun.satis_fiyat = float(urun.satis_fiyat)
        except ValueError:
            flash('Stok, alış/satış fiyatı sayı olmalıdır!', 'danger')
            return redirect(url_for('duzenle', id=id))

        db.session.commit()
        flash('Ürün başarıyla güncellendi!', 'success')
        return redirect(url_for('urun_listesi'))

    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('urun_duzenle.html', urun=urun, kategoriler=kategoriler)

@app.route('/<int:id>/sil', methods=('POST',))
@login_required
@role_required('admin') 
def sil(id):
    urun = Urun.query.get(id)
    if urun:
        db.session.delete(urun)
        db.session.commit()
        flash('Ürün başarıyla silindi!', 'info')
    else:
        flash('Ürün bulunamadı!', 'danger')
    return redirect(url_for('urun_listesi'))

@app.route('/musteri_ekle', methods=('GET', 'POST'))
@login_required
@role_required('admin') 
def musteri_ekle():
    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    if request.method == 'POST':
        ad_soyad = request.form['ad_soyad']
        telefon = request.form['telefon']
        adres = request.form['adres']
        eposta = request.form['eposta']

        if not ad_soyad:
            flash('Müşteri Adı Soyadı boş bırakılamaz!', 'danger')
            return redirect(url_for('musteri_ekle'))

        new_musteri = Musteri(ad_soyad=ad_soyad, telefon=telefon, adres=adres, eposta=eposta, ekleyen_kullanici_id=session['kullanici_id'])
        db.session.add(new_musteri)
        db.session.commit()
        flash('Müşteri başarıyla eklendi!', 'success')
        return redirect(url_for('satis_yap')) 

    return render_template('musteri_ekle.html', kategoriler=kategoriler)

@app.route('/musteri_duzenle/<int:id>', methods=('GET', 'POST'))
@login_required
@role_required('admin') 
def musteri_duzenle(id):
    musteri = Musteri.query.get(id)

    if musteri is None:
        flash('Müşteri bulunamadı!', 'danger')
        return redirect(url_for('musteri_gecmisi'))

    if request.method == 'POST':
        musteri.ad_soyad = request.form['ad_soyad']
        musteri.telefon = request.form['telefon']
        musteri.adres = request.form['adres']
        musteri.eposta = request.form['eposta']

        if not musteri.ad_soyad:
            flash('Müşteri Adı Soyadı boş bırakılamaz!', 'danger')
            return redirect(url_for('musteri_duzenle', id=id))

        db.session.commit()
        flash('Müşteri başarıyla güncellendi!', 'success')
        return redirect(url_for('musteri_gecmisi')) 

    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('musteri_duzenle.html', musteri=musteri, kategoriler=kategoriler)

@app.route('/ayarlar', methods=('GET', 'POST'))
@login_required
@role_required('admin') 
def ayarlar():
    ayarlar_obj = Ayar.query.first() 

    if request.method == 'POST':
        if not ayarlar_obj: 
            ayarlar_obj = Ayar()
            db.session.add(ayarlar_obj)

        ayarlar_obj.sirket_adi = request.form['sirket_adi']
        ayarlar_obj.adres = request.form['adres']
        ayarlar_obj.telefon = request.form['telefon']
        ayarlar_obj.eposta = request.form['eposta']
        düsuk_stok_esigi_str = request.form['düsuk_stok_esigi'] 
        
        try:
            ayarlar_obj.düsuk_stok_esigi = int(düsuk_stok_esigi_str)
            if ayarlar_obj.düsuk_stok_esigi < 0:
                flash('Düşük stok eşiği negatif olamaz!', 'danger')
                return redirect(url_for('ayarlar'))
        except ValueError:
            flash('Düşük stok eşiği sayı olmalıdır!', 'danger')
            return redirect(url_for('ayarlar'))

        db.session.commit()
        flash('Ayarlar başarıyla kaydedildi!', 'success')
        return redirect(url_for('ayarlar')) 
    
    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('ayarlar.html', sirket_bilgileri=ayarlar_obj, kategoriler=kategoriler)


@app.route('/satis_yap')
@login_required 
def satis_yap():
    urunler = Urun.query.order_by(Urun.ad).all()
    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    musteriler = Musteri.query.order_by(Musteri.ad_soyad).all()
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

    try:
        toplam_urun_fiyati = 0
        for item in cart:
            urun_id = item['id']
            satilan_adet = item['adet']
            
            urun = Urun.query.get(urun_id)
            if urun is None:
                db.session.rollback() 
                return jsonify({'success': False, 'message': f"Ürün (ID: {urun_id}) bulunamadı."}), 404
            
            if satilan_adet > urun.stok:
                db.session.rollback()
                return jsonify({'success': False, 'message': f"'{urun.ad}' için yeterli stok yok. Mevcut: {urun.stok}, İstenen: {satilan_adet}"}), 400
            
            toplam_urun_fiyati += urun.satis_fiyat * satilan_adet
        
        new_satis = Satis(musteri_id=musteri_id, satis_tarihi=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), toplam_urun_fiyati=toplam_urun_fiyati, iscilik_fiyati=iscilik_fiyati, ek_notlar=ek_notlar)
        db.session.add(new_satis)
        db.session.flush() 

        for item in cart:
            urun = Urun.query.get(item['id'])
            urun.stok -= item['adet'] 
            new_satis_detayi = SatisDetayi(satis_id=new_satis.id, urun_id=item['id'], satilan_adet=item['adet'], birim_satis_fiyati=urun.satis_fiyat)
            db.session.add(new_satis_detayi)
        
        db.session.commit() 
        return jsonify({'success': True, 'message': 'Satış başarıyla tamamlandı!', 'satis_id': new_satis.id}), 200

    except Exception as e:
        db.session.rollback() 
        return jsonify({'success': False, 'message': f"Satış sırasında bir hata oluştu: {str(e)}"}), 500

@app.route('/musteri_gecmisi')
@login_required 
def musteri_gecmisi():
    if session.get('rol') == 'admin':
        musteriler = Musteri.query.order_by(Musteri.ad_soyad).all()
    else: 
        musteriler = Musteri.query.filter_by(ekleyen_kullanici_id=session['kullanici_id']).order_by(Musteri.ad_soyad).all()
        
    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('musteri_gecmisi.html', musteriler=musteriler, kategoriler=kategoriler)

@app.route('/musteri_detay/<int:musteri_id>')
@login_required 
def musteri_detay(musteri_id):
    musteri = Musteri.query.get(musteri_id)
    if musteri is None:
        flash('Müşteri bulunamadı!', 'danger')
        return redirect(url_for('musteri_gecmisi'))
    
    if session.get('rol') != 'admin' and musteri.ekleyen_kullanici_id != session['kullanici_id']:
        flash('Bu müşterinin detaylarını görüntüleme yetkiniz yok!', 'danger')
        return redirect(url_for('musteri_gecmisi'))

    satislar = db.session.query(
        Satis
    ).filter(Satis.musteri_id == musteri_id)\
     .order_by(Satis.satis_tarihi.desc(), Satis.id.desc()).all()

    gruplanmis_satislar = {}
    for satis_obj in satislar:
        satis_id = satis_obj.id
        satis_dict = satis_obj.__dict__
        satis_dict.pop('_sa_instance_state', None)
        satis_dict['urunler'] = []
        gruplanmis_satislar[satis_id] = satis_dict
        
        satis_detaylari = db.session.query(
            SatisDetayi,
            Urun.ad.label('urun_ad'), Urun.birim.label('urun_birim')
        ).join(Urun, SatisDetayi.urun_id == Urun.id)\
         .filter(SatisDetayi.satis_id == satis_id).all()
        
        for detay_obj, urun_ad, urun_birim in satis_detaylari:
            detay_dict = detay_obj.__dict__
            detay_dict.pop('_sa_instance_state', None)
            detay_dict['urun_ad'] = urun_ad
            detay_dict['urun_birim'] = urun_birim
            gruplanmis_satislar[satis_id]['urunler'].append(detay_dict)
    
    satis_listesi = sorted(list(gruplanmis_satislar.values()), key=lambda x: x['satis_tarihi'], reverse=True)

    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    return render_template('musteri_detay.html', musteri=musteri, satislar=satis_listesi, kategoriler=kategoriler)

@app.route('/fatura/<int:satis_id>')
@login_required 
def fatura(satis_id):
    satis = Satis.query.get(satis_id)
    if satis is None:
        flash('Fatura bulunamadı!', 'danger')
        return redirect(url_for('anasayfa'))

    musteri = Musteri.query.get(satis.musteri_id)
    if musteri is None:
        flash('Müşteri bulunamadı!', 'danger')
        return redirect(url_for('anasayfa')) 

    urun_kalemleri_raw = db.session.query(
        SatisDetayi,
        Urun.ad.label('urun_ad'), Urun.birim.label('urun_birim')
    ).join(Urun, SatisDetayi.urun_id == Urun.id)\
     .filter(SatisDetayi.satis_id == satis_id).all()
    
    urun_kalemleri_for_template = []
    for kalem_obj, urun_ad, urun_birim in urun_kalemleri_raw:
        kalem_dict = kalem_obj.__dict__
        kalem_dict.pop('_sa_instance_state', None)
        kalem_dict['urun_ad'] = urun_ad
        kalem_dict['urun_birim'] = urun_birim
        urun_kalemleri_for_template.append(kalem_dict)


    sirket_bilgileri = Ayar.query.first()
    if sirket_bilgileri is None:
        sirket_bilgileri = Ayar(sirket_adi='Şirket Adı Yok', adres='', telefon='', eposta='') 
    
    kategoriler = Urun.query.with_entities(Urun.kategori).distinct().order_by(Urun.kategori).all()
    
    toplam_urun_fiyati = satis.toplam_urun_fiyati
    iscilik_fiyati = satis.iscilik_fiyati 
    genel_toplam = toplam_urun_fiyati + iscilik_fiyati

    return render_template('fatura.html', 
                           satis=satis, 
                           musteri=musteri, 
                           urun_kalemleri=urun_kalemleri_for_template, 
                           genel_toplam=genel_toplam,
                           sirket_bilgileri=sirket_bilgileri, 
                           kategoriler=kategoriler) 

# Uygulamayı çalıştır
if __name__ == '__main__':
    app.run(debug=True)