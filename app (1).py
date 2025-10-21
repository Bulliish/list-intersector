
import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="List Intersector (Contacts in Both Lists)", page_icon="🔗", layout="centered")

st.title("🔗 List Intersector")
st.caption("Upload two Excel files. We'll return the contacts that exist in **both** lists based on a matching key you choose (e.g., Company name or Email domain).")

with st.expander("How it works / assumptions", expanded=False):
    st.markdown("""
    - **List A**: the *reference list* (e.g., smaller list of target companies).
    - **List B**: the *contacts list* (larger list to filter down).
    - We create an **intersection** by matching a key you choose from each list.
    - Typical keys:
        - Company name → `Company` column in both lists.
        - Email domain → derived from an email column (e.g., `user@company.com` → `company.com`).
    - Matching options include: case-insensitive, whitespace trimming, punctuation & company-suffix cleanup (`Inc`, `LLC`, etc.).
    """)

# Sidebar options
st.sidebar.header("Options")
case_insensitive = st.sidebar.checkbox("Case-insensitive match", value=True)
trim_spaces = st.sidebar.checkbox("Trim surrounding whitespace", value=True)
normalize_company_suffixes = st.sidebar.checkbox("Normalize company names (drop Inc., LLC, Ltd., commas, periods, '& Co', etc.)", value=True)
strip_the_prefix = st.sidebar.checkbox('Strip leading "The "', value=True)
dedupe_on_key = st.sidebar.checkbox("Drop duplicate keys in each list before intersecting", value=True)
output_as_excel = st.sidebar.radio("Download format", options=["CSV (.csv)", "Excel (.xlsx)"], index=0)

def read_excel_with_picker(label_prefix):
    uploaded = st.file_uploader(f"Upload {label_prefix} Excel (.xlsx, .xls)", type=["xlsx", "xls"], key=f"{label_prefix}_uploader")
    if not uploaded:
        return None, None, None

    try:
        xl = pd.ExcelFile(uploaded)
        sheet = st.selectbox(f"{label_prefix}: choose sheet", options=xl.sheet_names, key=f"{label_prefix}_sheet")
        df = xl.parse(sheet_name=sheet)
    except Exception as e:
        st.error(f"Failed to read Excel: {e}")
        return None, None, None

    st.caption(f"{label_prefix} preview (first 10 rows):")
    st.dataframe(df.head(10), use_container_width=True)
    return df, sheet, uploaded.name

col1, col2 = st.columns(2)
with col1:
    df_a, sheet_a, name_a = read_excel_with_picker("List A (Reference)")

with col2:
    df_b, sheet_b, name_b = read_excel_with_picker("List B (Contacts)")

def email_to_domain(email: str):
    if not isinstance(email, str):
        return None
    email = email.strip()
    if '@' not in email:
        return None
    local, domain = email.split('@', 1)
    domain = domain.strip().lower()
    return domain

def normalize_key_series(s: pd.Series, for_company: bool) -> pd.Series:
    s = s.astype(str)
    if trim_spaces:
        s = s.str.strip()
    if case_insensitive:
        s = s.str.lower()
    if for_company and normalize_company_suffixes:
        # Remove punctuation (commas, periods, apostrophes)
        s = s.str.replace(r"[,\.\u2019']", "", regex=True)
        s = s.str.replace(r"\s*&\s*", " and ", regex=True)  # unify & as 'and'
        # Remove common suffixes
        suffix_pat = r"\b(incorporated|inc|llc|l\.l\.c|ltd|l\.t\.d|co|company|corp|corporation|gmbh|s\.a\.|srl|plc|bv|n\.v\.|ag|pte|pty|s\.r\.o\.|oy|ab|sas|sa|bvba|kg|kgaa)\b\.?"
        s = s.str.replace(suffix_pat, "", regex=True, case=False)
        s = s.str.replace(r"\s{2,}", " ", regex=True).str.strip()
    if for_company and strip_the_prefix:
        s = s.str.replace(r"^the\s+", "", regex=True, case=False)
    # Treat 'nan' or empty as NA
    s = s.where(~s.str.fullmatch(r"\s*nan\s*", case=False), other=pd.NA)
    s = s.where(s.str.len() > 0, other=pd.NA)
    return s

st.markdown("### Choose match keys")
if df_a is not None and df_b is not None:
    cols_a = list(df_a.columns)
    cols_b = list(df_b.columns)

    # Key selection for A
    key_type_a = st.selectbox("Key type for List A", options=["Company column", "Email → Domain derived"], index=0)
    if key_type_a == "Company column":
        col_key_a = st.selectbox("List A: Company column", options=cols_a, key="col_key_a")
        key_series_a = normalize_key_series(df_a[col_key_a], for_company=True)
    else:
        email_col_a = st.selectbox("List A: Email column (to derive domain)", options=cols_a, key="email_col_a")
        key_series_a = df_a[email_col_a].map(email_to_domain)
        key_series_a = normalize_key_series(key_series_a, for_company=False)

    # Key selection for B
    key_type_b = st.selectbox("Key type for List B", options=["Company column", "Email → Domain derived"], index=0, key="key_type_b")
    if key_type_b == "Company column":
        col_key_b = st.selectbox("List B: Company column", options=cols_b, key="col_key_b")
        key_series_b = normalize_key_series(df_b[col_key_b], for_company=True)
    else:
        email_col_b = st.selectbox("List B: Email column (to derive domain)", options=cols_b, key="email_col_b")
        key_series_b = df_b[email_col_b].map(email_to_domain)
        key_series_b = normalize_key_series(key_series_b, for_company=False)

    # Attach normalized keys
    df_a["_key_norm"] = key_series_a
    df_b["_key_norm"] = key_series_b

    if dedupe_on_key:
        df_a = df_a.drop_duplicates(subset=["_key_norm"], keep="first")
        df_b = df_b.drop_duplicates(subset=["_key_norm"], keep="first")

    run = st.button("🔍 Find Contacts in Both Lists", type="primary")

    if run:
        try:
            a_keys = set(df_a["_key_norm"].dropna().tolist())
            # Filter B down to rows whose key is in A
            b_in_both = df_b[df_b["_key_norm"].isin(a_keys)].copy()

            # Create an inner join for context (merge on normalized key)
            merged = pd.merge(
                df_a.drop(columns=["_key_norm"]),
                df_b.drop(columns=["_key_norm"]),
                left_index=False, right_index=False,
                left_on=df_a["_key_norm"],
                right_on=df_b["_key_norm"],
                how="inner",
                suffixes=("_A", "_B")
            )

            st.success(f"Found **{len(b_in_both)}** contact(s) in List B whose key matches List A. Unique keys in A: **{len(a_keys)}**.")

            st.subheader("Preview: Contacts in Both Lists (from List B)")
            st.dataframe(b_in_both.head(20), use_container_width=True)

            if output_as_excel.startswith("Excel"):
                # Excel downloads
                buf_b = io.BytesIO()
                with pd.ExcelWriter(buf_b, engine="xlsxwriter") as writer:
                    b_in_both.to_excel(writer, index=False, sheet_name="ContactsInBoth")
                st.download_button(
                    "⬇️ Download Contacts in Both (Excel)",
                    data=buf_b.getvalue(),
                    file_name="contacts_in_both.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                buf_m = io.BytesIO()
                with pd.ExcelWriter(buf_m, engine="xlsxwriter") as writer:
                    merged.to_excel(writer, index=False, sheet_name="InnerJoin")
                st.download_button(
                    "⬇️ Download Inner Join (Excel)",
                    data=buf_m.getvalue(),
                    file_name="inner_join_A_B.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                # CSV downloads
                csv_b = b_in_both.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Download Contacts in Both (CSV)",
                    data=csv_b,
                    file_name="contacts_in_both.csv",
                    mime="text/csv",
                )

                csv_m = merged.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Download Inner Join (CSV)",
                    data=csv_m,
                    file_name="inner_join_A_B.csv",
                    mime="text/csv",
                )

            with st.expander("Diagnostics"):
                st.json({
                    "sheet_a": sheet_a,
                    "sheet_b": sheet_b,
                    "key_type_a": key_type_a,
                    "key_type_b": key_type_b,
                    "case_insensitive": case_insensitive,
                    "trim_spaces": trim_spaces,
                    "normalize_company_suffixes": normalize_company_suffixes,
                    "strip_the_prefix": strip_the_prefix,
                    "dedupe_on_key": dedupe_on_key,
                    "output_format": "csv" if output_as_excel.startswith("CSV") else "xlsx",
                    "rows_list_a": len(df_a),
                    "rows_list_b": len(df_b),
                })

        except KeyError as e:
            st.error(f"Key column not found: {e}")
        except Exception as e:
            st.exception(e)

st.markdown("---")
st.caption("Tip: If your smaller list contains companies, pick **Company column** for both. If your lists don't share exact company names, consider matching by **Email → Domain derived**.")
