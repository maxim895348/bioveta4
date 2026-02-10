import streamlit as st
import pandas as pd
import re
from datetime import datetime
import io

# --- НАСТРОЙКИ ---
st.set_page_config(page_title="GMP Auto-Audit", layout="wide")

# --- ФУНКЦИИ АВТО-ПИЛОТА ---

def clean_header(df):
    """Лечит ошибку JSON: убирает пустые имена колонок"""
    df.columns = [str(c).strip() if pd.notna(c) and str(c).strip() != "" else f"Col_{i}" for i, c in enumerate(df.columns)]
    return df

def find_header_row(df, keywords):
    """Сканирует файл вниз, пока не найдет ключевые слова"""
    for i in range(min(50, len(df))):
        row_text = " ".join([str(x).lower() for x in df.iloc[i].values])
        # Если нашли хотя бы 2 совпадения (например "производитель" и "наименование")
        if sum(1 for k in keywords if k in row_text) >= 1:
            return i
    return None

def load_smart(uploaded_file, file_type):
    """Умная загрузка: сама ищет шапку и данные"""
    try:
        # 1. Читаем сырые данные
        df = None
        if uploaded_file.name.lower().endswith('.csv'):
            for enc in ['utf-8', 'cp1251', 'latin1']:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=enc, sep=None, engine='python')
                    if df.shape[1] > 1: break
                except: continue
        else:
            df = pd.read_excel(uploaded_file, header=None)
        
        if df is None: return None, "Нечитаемый файл"

        # 2. Ищем заголовки (Определяем ключевые слова)
        keywords = []
        if file_type == "REG": keywords = ["торговое", "наименование", "лекарственная"]
        else: keywords = ["перечень", "производител", "срок"]
        
        idx = find_header_row(df, keywords)
        
        if idx is not None:
            # Нашли шапку - отрезаем лишнее сверху
            df.columns = df.iloc[idx]
            df = df.iloc[idx+1:].reset_index(drop=True)
            df = clean_header(df) # Санитарная обработка имен
            return df, None
        
        # Если шапку не нашли — возвращаем как есть (Blind mode), но чистим колонки
        df = clean_header(df)
        return df, "No Header Found"

    except Exception as e:
        return None, str(e)

def get_col_by_keyword(df, keywords):
    """Ищет колонку по смыслу, а не точному названию"""
    for col in df.columns:
        c_str = str(col).lower()
        if any(k in c_str for k in keywords):
            return col
    # Если не нашли по имени, возвращаем по индексу (эвристика)
    # Для РУ: 0 - Название, 1 - МНН, ... 6 - Производитель
    # Для GMP: 1 - Производитель, 8 - Перечень
    return None

def parse_date_status(date_str):
    if pd.isna(date_str): return "Нет данных", None
    text = str(date_str).lower()
    if "истек" in text: return "Expired", None
    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', text)
    if match:
        try:
            d = datetime.strptime(match.group(1), '%d.%m.%Y')
            return ("Active", d) if d > datetime.now() else ("Expired", d)
        except: pass
    return "Active", None # Если даты нет, но и "истек" нет, считаем условно активным (риск)

def extract_drugs(text):
    if pd.isna(text): return []
    s = str(text)
    s = re.sub(r'\n', ';', s).replace('1)', ';').replace('2)', ';')
    if ';' not in s and ',' in s: s = s.replace(',', ';')
    return [d.strip().lower() for d in s.split(';') if len(d.strip()) > 2]

# --- ИНТЕРФЕЙС ---
st.title("⚡ GMP Auto-Audit (Без настроек)")
st.markdown("Просто загрузи два файла. Система сама найдет колонки и сопоставит данные.")

c1, c2 = st.columns(2)
f_reg = c1.file_uploader("1. Список РУ (Препараты)", key="f1")
f_gmp = c2.file_uploader("2. База GMP (Иностранные)", key="f2")

if f_reg and f_gmp:
    with st.spinner("Автоматический анализ структуры файлов..."):
        # 1. Загрузка
        df_reg, msg1 = load_smart(f_reg, "REG")
        df_gmp, msg2 = load_smart(f_gmp, "GMP")
        
        if df_reg is None or df_gmp is None:
            st.error("Ошибка чтения файлов. Убедитесь, что это Excel/CSV.")
        else:
            # 2. Авто-определение колонок
            # РУ
            col_name = get_col_by_keyword(df_reg, ["торговое", "наименование", "препарат"]) or df_reg.columns[0]
            col_mfg_reg = get_col_by_keyword(df_reg, ["производител", "фирма", "держатель"])
            
            # GMP
            col_list = get_col_by_keyword(df_gmp, ["перечень", "продукция", "лекарствен"]) or df_gmp.columns[-1]
            col_mfg_gmp = get_col_by_keyword(df_gmp, ["производител", "фирма"]) or df_gmp.columns[1]
            col_date = get_col_by_keyword(df_gmp, ["срок", "дата", "окончание"])
            
            # 3. Создание базы поиска (Lookup)
            gmp_db = []
            for _, row in df_gmp.iterrows():
                try:
                    st_val, dt = parse_date_status(row[col_date] if col_date else None)
                    drugs = extract_drugs(row[col_list])
                    mfg = str(row[col_mfg_gmp]).strip().lower()
                    for d in drugs:
                        gmp_db.append({'d': d, 'm': mfg, 's': st_val, 'dt': dt})
                except: continue
            
            lookup = pd.DataFrame(gmp_db)
            
            # 4. Анализ
            results = []
            for _, row in df_reg.iterrows():
                r_name = str(row[col_name]).strip()
                r_mfg = str(row[col_mfg_reg]).strip() if col_mfg_reg else ""
                
                # Логика поиска: Первое слово названия
                # "Биокан DHPPi" -> "биокан"
                tokens = re.split(r'[ \-\(\)\.\,]+', r_name.lower())
                key = next((t for t in tokens if len(t) > 2), "")
                
                status = "❌ GMP NOT FOUND"
                details = "Сертификат не найден"
                bg = "#FECACA"
                
                if key and not lookup.empty:
                    hits = lookup[lookup['d'].str.contains(key, regex=False, na=False)]
                    if not hits.empty:
                        # Проверяем активные
                        active = hits[hits['s'] == 'Active']
                        if not active.empty:
                            best = active.iloc[0]
                            status = "✅ OK"
                            date_str = best['dt'].strftime('%d.%m.%Y') if best['dt'] else "Бессрочно/Активен"
                            details = f"Действует до {date_str}"
                            bg = "#D1FAE5"
                        else:
                            status = "⚠️ EXPIRED"
                            details = "Сертификат найден, но истек"
                            bg = "#FEF3C7"
                
                results.append({
                    'Препарат (РУ)': r_name,
                    'Статус': status,
                    'Детали': details,
                    'Производитель': r_mfg,
                    '_bg': bg
                })
            
            final_df = pd.DataFrame(results)
            
            # 5. Вывод
            st.success(f"Анализ завершен. Проверено {len(final_df)} препаратов.")
            
            def color_rows(row):
                return [f'background-color: {row["_bg"]}'] * len(row)

            st.dataframe(
                final_df.style.apply(color_rows, axis=1),
                column_config={"_bg": None},
                use_container_width=True,
                height=800
            )
            
            csv = final_df.drop(columns=['_bg']).to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Скачать результат", csv, "audit_result.csv", "text/csv", type="primary")
