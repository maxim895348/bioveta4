import streamlit as st
import pandas as pd
import re
from datetime import datetime
import io

# --- КОНФИГУРАЦИЯ ---
st.set_page_config(page_title="Reg vs GMP Cross-Check V5", layout="wide")

# --- ФУНКЦИИ ---
def clean_text(text):
    return str(text).strip() if not pd.isna(text) else ""

def parse_date_status(date_str):
    if pd.isna(date_str): return "Нет данных", None
    text = str(date_str).lower()
    if "истек" in text: return "Expired", None
    
    # Ищем дату (поддержка разных форматов)
    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', text)
    if match:
        try:
            d = datetime.strptime(match.group(1), '%d.%m.%Y')
            return ("Active", d) if d > datetime.now() else ("Expired", d)
        except: pass
    return "Unknown", None

def extract_drugs_gmp(drug_text):
    """Парсинг списка из GMP файла"""
    if pd.isna(drug_text): return []
    text = str(drug_text)
    # Заменяем переносы и нумерацию
    text = re.sub(r'\n', ';', text)
    text = re.sub(r'\d+\)', ';', text)
    text = re.sub(r'\d+\.', ';', text)
    # Если разделитель запятая, а точки с запятой нет
    if ';' not in text and ',' in text:
        text = text.replace(',', ';')
        
    return [d.strip().lower() for d in text.split(';') if len(d.strip()) > 2]

def find_header_smart(df, keywords):
    """Ищет строку заголовков, игнорируя регистр"""
    for i in range(min(30, len(df))):
        # Превращаем строку в нижний регистр и склеиваем в один текст для поиска
        row_text = " ".join([str(x).lower() for x in df.iloc[i].values])
        
        # Если найдено хотя бы одно ключевое слово
        for k in keywords:
            if k in row_text:
                return i
    return None

def robust_read_csv(uploaded_file):
    """Перебирает кодировки и разделители, чтобы прочитать CSV"""
    encodings = ['utf-8', 'cp1251', 'latin1']
    separators = [',', ';', '\t']
    
    for enc in encodings:
        for sep in separators:
            try:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding=enc, sep=sep)
                # Если в таблице больше 1 колонки, скорее всего угадали
                if df.shape[1] > 1:
                    return df
            except:
                continue
    return None

def load_file_smart(uploaded_file, file_type="unknown"):
    try:
        df = None
        # 1. Читаем файл в зависимости от расширения
        if uploaded_file.name.lower().endswith('.csv'):
            df = robust_read_csv(uploaded_file)
            if df is None: return None, "Не удалось прочитать CSV (проблемы с кодировкой)"
        else:
            df = pd.read_excel(uploaded_file, header=None)
        
        # 2. Ищем заголовки
        idx = None
        keywords = []
        
        if file_type == "REGISTRY":
            # Ищем слова для файла РУ
            keywords = ["торговое", "лекарственная", "регистрационный"]
        else:
            # Ищем слова для файла GMP
            keywords = ["перечень", "производител", "адрес"]
            
        idx = find_header_smart(df, keywords)
            
        if idx is not None:
            # Ставим правильный заголовок
            df.columns = df.iloc[idx]
            df = df.iloc[idx+1:].reset_index(drop=True)
            return df, None
        else:
            # DEBUG: Если не нашли, покажем первые строки пользователю в ошибке
            preview = df.head(3).to_string()
            return df, f"Заголовки не найдены. Ключевые слова: {keywords}. \nПроверьте, что файл читается корректно. Первые строки:\n{preview}"
            
    except Exception as e:
        return None, str(e)

def highlight_rows(row):
    color = row.get('_bg', '#ffffff') 
    return [f'background-color: {color}'] * len(row)

# --- ИНТЕРФЕЙС ---
st.title("⚖️ Cross-Check: Регистрация vs GMP (V5 Robust)")
st.markdown("Сверка списка **Зарегистрированных препаратов (РУ)** с наличием **Сертификата GMP**.")

col1, col2 = st.columns(2)
with col1:
    st.info("1. Файл с препаратами (РУ)")
    file_reg = st.file_uploader("Загрузить список (18 препаратов)", key="reg")
with col2:
    st.info("2. Файл GMP (Иностранные)")
    file_gmp = st.file_uploader("Загрузить базу GMP", key="gmp")

if st.button("ПРОВЕРИТЬ ЛЕГИТИМНОСТЬ ВВОЗА", type="primary"):
    if file_reg and file_gmp:
        with st.spinner("Анализ..."):
            
            # ЗАГРУЗКА
            df_reg, err1 = load_file_smart(file_reg, "REGISTRY")
            df_gmp, err2 = load_file_smart(file_gmp, "GMP")
            
            # ОБРАБОТКА ОШИБОК ЗАГРУЗКИ
            if err1: 
                st.error(f"Ошибка в файле РУ: {err1}")
                if df_reg is not None: st.dataframe(df_reg.head()) # Показать сырые данные
            elif err2: 
                st.error(f"Ошибка в файле GMP: {err2}")
                if df_gmp is not None: st.dataframe(df_gmp.head())
            else:
                # ПОИСК КОЛОНОК
                col_name_reg = next((c for c in df_reg.columns if 'торговое' in str(c).lower()), None)
                col_mfg_reg = next((c for c in df_reg.columns if 'производител' in str(c).lower()), None)
                
                col_list_gmp = next((c for c in df_gmp.columns if 'перечень' in str(c).lower()), None)
                col_date_gmp = next((c for c in df_gmp.columns if 'срок' in str(c).lower()), None)
                col_mfg_gmp = next((c for c in df_gmp.columns if 'производител' in str(c).lower()), None)

                # Если колонки не найдены — выводим список того, что нашли
                if not (col_name_reg and col_list_gmp):
                    st.error("Не найдены нужные колонки!")
                    c1, c2 = st.columns(2)
                    c1.write("Колонки в файле РУ:", list(df_reg.columns))
                    c2.write("Колонки в файле GMP:", list(df_gmp.columns))
                else:
                    # БИЗНЕС-ЛОГИКА
                    
                    # 1. Готовим справочник GMP
                    gmp_db = []
                    for _, row in df_gmp.iterrows():
                        status, dt = parse_date_status(row[col_date_gmp] if col_date_gmp else None)
                        drugs = extract_drugs_gmp(row[col_list_gmp])
                        mfg = clean_text(row[col_mfg_gmp]).lower()
                        for d in drugs:
                            gmp_db.append({'drug': d, 'mfg': mfg, 'status': status, 'date': dt})
                    df_gmp_lookup = pd.DataFrame(gmp_db)

                    # 2. Проверяем каждый препарат из списка РУ
                    results = []
                    for _, row in df_reg.iterrows():
                        reg_name = clean_text(row[col_name_reg])
                        reg_mfg = clean_text(row[col_mfg_reg]) if col_mfg_reg else ""
                        
                        match_status = "❌ GMP NOT FOUND"
                        match_details = "Препарат есть в РУ, но GMP на него нет"
                        bg_color = "#FECACA" # Красный
                        
                        if not df_gmp_lookup.empty:
                            # Поиск по первому слову названия (First Token Match)
                            # "Биокан DHPPi" -> ищем "биокан"
                            tokens = re.split(r'[ \-\(\)]+', reg_name.lower())
                            search_key = tokens[0] if len(tokens) > 0 else ""
                            
                            if len(search_key) > 2: # Не ищем короткие слова
                                candidates = df_gmp_lookup[df_gmp_lookup['drug'].str.contains(search_key, regex=False, na=False)]
                                
                                if not candidates.empty:
                                    # Проверяем статус
                                    active = candidates[candidates['status'] == 'Active']
                                    if not active.empty:
                                        best = active.iloc[0]
                                        match_status = "✅ OK"
                                        match_details = f"Действует до {best['date'].strftime('%d.%m.%Y')}"
                                        bg_color = "#D1FAE5" # Зеленый
                                    else:
                                        match_status = "⚠️ EXPIRED"
                                        match_details = "GMP сертификат истек"
                                        bg_color = "#FEF3C7" # Желтый
                        
                        results.append({
                            'Препарат (РУ)': reg_name,
                            'Статус GMP': match_status,
                            'Детали': match_details,
                            'Производитель (РУ)': reg_mfg,
                            '_bg': bg_color
                        })
                    
                    df_final = pd.DataFrame(results)
                    
                    # МЕТРИКИ
                    ok_count = len(df_final[df_final['Статус GMP'].str.contains("OK")])
                    
                    st.divider()
                    m1, m2 = st.columns(2)
                    m1.metric("Всего позиций в РУ", len(df_final))
                    m2.metric("Легитимны для ввоза (GMP OK)", ok_count)
                    
                    # ТАБЛИЦА
                    styler = df_final.style.apply(highlight_rows, axis=1)
                    st.dataframe(
                        styler,
                        column_config={"_bg": None}, # Скрываем колонку цвета
                        use_container_width=True,
                        height=600
                    )
                    
                    # СКАЧИВАНИЕ
                    csv = df_final.drop(columns=['_bg']).to_csv(index=False).encode('utf-8-sig')
                    st.download_button("Скачать отчет (CSV)", csv, "cross_check_result.csv", "text/csv", type="primary")

    else:
        st.warning("Загрузите оба файла для начала работы.")
