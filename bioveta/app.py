import streamlit as st
import pandas as pd
import re
from datetime import datetime
import io

# --- КОНФИГУРАЦИЯ ---
st.set_page_config(page_title="Reg vs GMP Cross-Check V6", layout="wide")

# --- ФУНКЦИИ ---
def clean_text(text):
    return str(text).strip() if not pd.isna(text) else ""

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
    return "Unknown", None

def extract_drugs_gmp(drug_text):
    if pd.isna(drug_text): return []
    text = str(drug_text)
    text = re.sub(r'\n', ';', text).replace('1)', ';').replace('2)', ';')
    if ';' not in text and ',' in text: text = text.replace(',', ';')
    return [d.strip().lower() for d in text.split(';') if len(d.strip()) > 2]

def find_header_smart(df, keywords):
    for i in range(min(30, len(df))):
        row_text = " ".join([str(x).lower() for x in df.iloc[i].values])
        if any(k in row_text for k in keywords): return i
    return None

def robust_read_csv(uploaded_file):
    encodings = ['utf-8', 'cp1251', 'latin1']
    separators = [',', ';', '\t']
    for enc in encodings:
        for sep in separators:
            try:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding=enc, sep=sep)
                if df.shape[1] > 1: return df
            except: continue
    return None

def load_file_smart(uploaded_file, file_type="unknown"):
    try:
        df = None
        if uploaded_file.name.lower().endswith('.csv'):
            df = robust_read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file, header=None)
            
        if df is None: return None, "Не удалось прочитать файл."

        # Поиск заголовков
        keywords = ["торговое", "наименование"] if file_type == "REGISTRY" else ["перечень", "производител"]
        idx = find_header_smart(df, keywords)
        
        if idx is not None:
            df.columns = df.iloc[idx]
            df = df.iloc[idx+1:].reset_index(drop=True)
            return df, None
        else:
            # FALLBACK: Если заголовки не найдены, возвращаем как есть (Blind Mode)
            # Будем использовать индексы колонок (0, 1, 2...)
            df.columns = [f"Col_{i}" for i in range(df.shape[1])]
            return df, "WARNING_NO_HEADER"
            
    except Exception as e:
        return None, str(e)

def highlight_rows(row):
    color = row.get('_bg', '#ffffff') 
    return [f'background-color: {color}'] * len(row)

# --- ИНТЕРФЕЙС ---
st.title("⚖️ Cross-Check: Регистрация vs GMP (Final)")

col1, col2 = st.columns(2)
with col1:
    st.info("1. Файл с препаратами (РУ)")
    file_reg = st.file_uploader("Загрузить список РУ", key="reg")
with col2:
    st.info("2. Файл GMP (Иностранные)")
    file_gmp = st.file_uploader("Загрузить базу GMP", key="gmp")

if st.button("ЗАПУСТИТЬ АНАЛИЗ", type="primary"):
    if file_reg and file_gmp:
        with st.spinner("Анализ..."):
            
            # ЗАГРУЗКА
            df_reg, msg1 = load_file_smart(file_reg, "REGISTRY")
            df_gmp, msg2 = load_file_smart(file_gmp, "GMP")
            
            if df_reg is None: st.error(f"Ошибка РУ: {msg1}")
            elif df_gmp is None: st.error(f"Ошибка GMP: {msg2}")
            else:
                # ОПРЕДЕЛЕНИЕ КОЛОНОК (SMART OR BLIND)
                
                # Файл РУ
                if msg1 == "WARNING_NO_HEADER":
                    st.warning("⚠️ В файле РУ не найдены заголовки. Используем 1-ю колонку как Название, 2-ю как Производителя.")
                    col_name_reg = df_reg.columns[0] # Берем 1-ю колонку
                    col_mfg_reg = df_reg.columns[1] if len(df_reg.columns) > 1 else None
                else:
                    col_name_reg = next((c for c in df_reg.columns if 'торговое' in str(c).lower() or 'наименование' in str(c).lower()), df_reg.columns[0])
                    col_mfg_reg = next((c for c in df_reg.columns if 'производител' in str(c).lower()), None)

                # Файл GMP
                if msg2 == "WARNING_NO_HEADER":
                    st.warning("⚠️ В файле GMP не найдены заголовки. Ищем перечень в последних колонках.")
                    col_list_gmp = df_gmp.columns[-1] # Обычно перечень в конце
                    col_date_gmp = df_gmp.columns[-2] if len(df_gmp.columns) > 1 else None
                    col_mfg_gmp = df_gmp.columns[1] if len(df_gmp.columns) > 1 else None
                else:
                    col_list_gmp = next((c for c in df_gmp.columns if 'перечень' in str(c).lower()), None)
                    col_date_gmp = next((c for c in df_gmp.columns if 'срок' in str(c).lower()), None)
                    col_mfg_gmp = next((c for c in df_gmp.columns if 'производител' in str(c).lower()), None)

                # DEBUG INFO
                with st.expander("Техническая информация о колонках"):
                    st.write(f"РУ Название: {col_name_reg}")
                    st.write(f"GMP Перечень: {col_list_gmp}")

                if not (col_name_reg and col_list_gmp):
                    st.error("Критическая ошибка: Не удалось определить колонки с названиями препаратов.")
                else:
                    # БИЗНЕС-ЛОГИКА
                    
                    # 1. Справочник GMP
                    gmp_db = []
                    for _, row in df_gmp.iterrows():
                        status, dt = parse_date_status(row[col_date_gmp] if col_date_gmp else None)
                        drugs = extract_drugs_gmp(row[col_list_gmp])
                        mfg = clean_text(row[col_mfg_gmp]) if col_mfg_gmp else ""
                        for d in drugs:
                            gmp_db.append({'drug': d, 'mfg': mfg.lower(), 'status': status, 'date': dt})
                    df_gmp_lookup = pd.DataFrame(gmp_db)

                    # 2. Анализ РУ
                    results = []
                    for _, row in df_reg.iterrows():
                        reg_name = clean_text(row[col_name_reg])
                        reg_mfg = clean_text(row[col_mfg_reg]) if col_mfg_reg else ""
                        
                        match_status = "❌ GMP NOT FOUND"
                        match_details = "Нет действующего сертификата"
                        bg_color = "#FECACA"
                        
                        if not df_gmp_lookup.empty:
                            # Поиск по первому слову
                            tokens = re.split(r'[ \-\(\)\.\,]+', reg_name.lower())
                            search_key = next((t for t in tokens if len(t) > 2), "")
                            
                            if search_key:
                                candidates = df_gmp_lookup[df_gmp_lookup['drug'].str.contains(search_key, regex=False, na=False)]
                                if not candidates.empty:
                                    active = candidates[candidates['status'] == 'Active']
                                    if not active.empty:
                                        best = active.iloc[0]
                                        match_status = "✅ OK"
                                        match_details = f"GMP до {best['date'].strftime('%d.%m.%Y')}"
                                        bg_color = "#D1FAE5"
                                    else:
                                        match_status = "⚠️ EXPIRED"
                                        match_details = "GMP истек"
                                        bg_color = "#FEF3C7"
                        
                        results.append({
                            'Препарат (РУ)': reg_name,
                            'Статус': match_status,
                            'Инфо': match_details,
                            'Производитель': reg_mfg,
                            '_bg': bg_color
                        })
                    
                    df_final = pd.DataFrame(results)
                    
                    # ВЫВОД
                    st.divider()
                    ok = len(df_final[df_final['Статус'].str.contains("OK")])
                    k1, k2 = st.columns(2)
                    k1.metric("Всего в списке", len(df_final))
                    k2.metric("Разрешен ввоз", ok)
                    
                    styler = df_final.style.apply(highlight_rows, axis=1)
                    st.dataframe(
                        styler,
                        column_config={"_bg": None},
                        use_container_width=True,
                        height=600
                    )
                    
                    csv = df_final.drop(columns=['_bg']).to_csv(index=False).encode('utf-8-sig')
                    st.download_button("Скачать результат", csv, "result.csv", "text/csv", type="primary")
    else:
        st.warning("Загрузите файлы.")
