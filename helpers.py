import pandas as pd
import numpy as np
import re
import os
import math
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_predict, StratifiedKFold
import matplotlib.pyplot as plt
from datetime import timedelta
from sklearn import metrics
from sklearn.metrics import roc_curve, auc, precision_recall_curve, average_precision_score, confusion_matrix, accuracy_score
from sklearn.metrics import roc_curve as sklearn_roc_curve
from sklearn.metrics import average_precision_score
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import LabelEncoder
from tensorflow.keras.utils import Sequence
from tensorflow.keras.preprocessing.sequence import pad_sequences
import collections

def convert_str_to_float(x):
    if isinstance(x, str):
        x_split = re.compile('[^a-zA-Z0-9-]').split(x.strip())
        if '-' in x_split[0]:
            x_split_dash = x_split[0].split('-')
            if len(x_split_dash) == 2 and x_split_dash[0].isnumeric() and x_split_dash[1].isnumeric():
                return (float(x_split_dash[0]) + float(x_split_dash[1])) / 2
            else:
                return np.nan
        else:
            if x_split[0].isnumeric():
                return float(x_split[0])
            else:
                return np.nan
    else:
        return x
        
def read_edstays_table(edstays_table_path):
    df_edstays = pd.read_csv(edstays_table_path)
    df_edstays['intime'] = pd.to_datetime(df_edstays['intime'])
    df_edstays['outtime'] = pd.to_datetime(df_edstays['outtime'])
    return df_edstays

def read_patients_table(patients_table_path):
    df_patients = pd.read_csv(patients_table_path)
    df_patients['dod'] = pd.to_datetime(df_patients['dod'])
    return df_patients

def read_admissions_table(admissions_table_path):
    df_admissions = pd.read_csv(admissions_table_path)
    df_admissions = df_admissions.rename(columns={"race": "ethnicity"})
    df_admissions =  df_admissions[['subject_id', 'hadm_id', 'admittime', 'dischtime', 'deathtime','ethnicity', 'edregtime','edouttime', 'insurance']]
    df_admissions['admittime'] = pd.to_datetime(df_admissions['admittime'])
    df_admissions['dischtime'] = pd.to_datetime(df_admissions['dischtime'])
    df_admissions['deathtime'] = pd.to_datetime(df_admissions['deathtime'])
    return df_admissions

def read_icustays_table(icustays_table_path):
    df_icu = pd.read_csv(icustays_table_path)
    df_icu['intime'] = pd.to_datetime(df_icu['intime'])
    df_icu['outtime'] = pd.to_datetime(df_icu['outtime'])
    return df_icu

def read_triage_table(triage_table_path):
    df_triage = pd.read_csv(triage_table_path)
    vital_rename_dict = {vital: '_'.join(['triage', vital]) for vital in ['temperature', 'heartrate', 'resprate', 'o2sat', 'sbp', 'dbp', 'pain', 'acuity']}
    df_triage.rename(vital_rename_dict, axis=1, inplace=True)
    df_triage['triage_pain'] = df_triage['triage_pain'].apply(convert_str_to_float).astype(float)

    return df_triage

def read_diagnoses_table(diagnoses_table_path):
    df_diagnoses = pd.read_csv(diagnoses_table_path)
    return df_diagnoses

def read_vitalsign_table(vitalsign_table_path):
    df_vitalsign = pd.read_csv(vitalsign_table_path)
    vital_rename_dict = {vital: '_'.join(['ed', vital]) for vital in
                         ['temperature', 'heartrate', 'resprate', 'o2sat', 'sbp', 'dbp', 'rhythm', 'pain']}
    df_vitalsign.rename(vital_rename_dict, axis=1, inplace=True)

    df_vitalsign['ed_pain'] = df_vitalsign['ed_pain'].apply(convert_str_to_float).astype(float)
    return df_vitalsign

def read_pyxis_table(pyxis_table_path):
    df_pyxis = pd.read_csv(pyxis_table_path)
    return df_pyxis

def merge_edstays_patients_on_subject(df_edstays,df_patients):
    if 'gender' in df_edstays.columns:
        df_edstays = pd.merge(df_edstays, df_patients[['subject_id', 'anchor_age', 'anchor_year','dod']], on = ['subject_id'], how='left')
    else:
        df_edstays = pd.merge(df_edstays, df_patients[['subject_id', 'anchor_age', 'gender', 'anchor_year','dod']], on = ['subject_id'], how='left')
    return df_edstays

def merge_edstays_admissions_on_subject(df_edstays ,df_admissions):
    df_edstays = pd.merge(df_edstays,df_admissions, on = ['subject_id', 'hadm_id'], how='left')
    return df_edstays

def merge_edstays_triage_on_subject(df_master ,df_triage):
    df_master = pd.merge(df_master,df_triage, on = ['subject_id', 'stay_id'], how='left')
    return df_master

def add_age(df_master):
    df_master['in_year'] = df_master['intime'].dt.year
    df_master['age'] = df_master['in_year'] - df_master['anchor_year'] + df_master['anchor_age']
    #df_master.drop(['anchor_age', 'anchor_year', 'in_year'],axis=1, inplace=True)
    return df_master

def add_inhospital_mortality(df_master):
    inhospital_mortality = df_master['dod'].notnull() & (df_master['dischtime'] >= df_master['dod'])
    df_master['outcome_inhospital_mortality'] = inhospital_mortality
    return df_master

def add_ed_los(df_master):
    ed_los = df_master['outtime'] - df_master['intime']
    df_master['ed_los'] = ed_los
    return df_master


def add_outcome_icu_transfer(df_master, df_icustays, timerange):
    timerange_delta = timedelta(hours = timerange)
    df_icustays_sorted = df_icustays[['subject_id', 'hadm_id', 'intime']].sort_values('intime')
    df_icustays_keep_first = df_icustays_sorted.groupby('hadm_id').first().reset_index()
    df_master_icu = pd.merge(df_master, df_icustays_keep_first, on = ['subject_id', 'hadm_id'], how='left', suffixes=('','_icu'))
    time_diff = (df_master_icu['intime_icu']- df_master_icu['outtime'])
    df_master_icu['time_to_icu_transfer'] = time_diff
    df_master_icu[''.join(['outcome_icu_transfer_', str(timerange), 'h'])] = time_diff <= timerange_delta
    # df_master_icu.drop(['intime_icu', 'time_to_icu_transfer'],axis=1, inplace=True)
    return df_master_icu

def fill_na_ethnicity(df_master): # requires df_master to be sorted 
    N = len(df_master)
    ethnicity_list= [float("NaN") for _ in range(N)]
    ethnicity_dict = {} # dict to store subejct ethnicity

    def get_filled_ethnicity(row):
        i = row.name
        if i % 10000 == 0:
            print('Process: %d/%d' % (i, N), end='\r')
        curr_eth = row['ethnicity']
        curr_subject = row['subject_id']
        prev_subject = df_master['subject_id'][i+1] if i< (N-1) else None

        if curr_subject not in ethnicity_dict.keys(): ## if subject ethnicity not stored yet, look ahead and behind 
            subject_ethnicity_list = []
            next_subject_idx = i+1
            prev_subject_idx = i-1
            next_subject= df_master['subject_id'][next_subject_idx] if next_subject_idx <= (N-1) else None
            prev_subject= df_master['subject_id'][prev_subject_idx] if prev_subject_idx >= 0 else None

            subject_ethnicity_list.append(df_master['ethnicity'][i]) ## add current ethnicity to list

            while prev_subject == curr_subject:
                subject_ethnicity_list.append(df_master['ethnicity'][prev_subject_idx])
                prev_subject_idx -= 1
                prev_subject= df_master['subject_id'][prev_subject_idx] if prev_subject_idx >= 0 else None

            while next_subject == curr_subject:
                subject_ethnicity_list.append(df_master['ethnicity'][next_subject_idx])
                next_subject_idx += 1
                next_subject= df_master['subject_id'][next_subject_idx] if next_subject_idx <= (N-1) else None
        
            eth_counter_list = collections.Counter(subject_ethnicity_list).most_common() #sorts counter and outputs list
            
            if len(eth_counter_list) == 0: ## no previous or next entries 
                subject_eth = curr_eth
            elif len(eth_counter_list) == 1: ## exactly one other ethnicity
                subject_eth = eth_counter_list.pop(0)[0] ## extract ethnicity from count tuple
            else:
                eth_counter_list = [x for x in eth_counter_list if pd.notna(x[0])] # remove any NA
                subject_eth = eth_counter_list.pop(0)[0]
            
            ethnicity_dict[curr_subject] = subject_eth ## store in dict
    
        if pd.isna(curr_eth): ## if curr_eth is na, fill with subject_eth from dict
            ethnicity_list[i]= ethnicity_dict[curr_subject]
        else:
            ethnicity_list[i]= curr_eth
            
    df_master.apply(get_filled_ethnicity, axis=1)
    print('Process: %d/%d' % (N, N), end='\r')
    df_master.loc[:,'ethnicity'] = ethnicity_list
    return df_master


def generate_past_ed_visits(df_master, timerange):
    #df_master = df_master.sort_values(['subject_id', 'intime']).reset_index()
    
    timerange_delta = timedelta(days=timerange)
    N = len(df_master)
    n_ed = [0 for _ in range(N)]

    def get_num_past_ed_visits(df):
        start = df.index[0]
        for i in df.index:
            if i % 10000 == 0:
                print('Process: %d/%d' % (i, N), end='\r')
            while df.loc[i, 'intime'] - df.loc[start, 'intime'] > timerange_delta:
                start += 1
            n_ed[i] = i - start

    grouped = df_master.groupby('subject_id')
    grouped.apply(get_num_past_ed_visits)
    print('Process: %d/%d' % (N, N), end='\r')

    df_master.loc[:, ''.join(['n_ed_', str(timerange), "d"])] = n_ed

    return df_master

def generate_past_admissions(df_master, df_admissions, timerange):
    df_admissions_sorted = df_admissions[df_admissions['subject_id'].isin(df_master['subject_id'].unique().tolist())][['subject_id', 'admittime']].copy()
    
    df_admissions_sorted.loc[:,'admittime'] = pd.to_datetime(df_admissions_sorted['admittime'])
    df_admissions_sorted.sort_values(['subject_id', 'admittime'], inplace=True)
    df_admissions_sorted.reset_index(drop=True, inplace=True)

    timerange_delta = timedelta(days=timerange)

    N = len(df_master)
    n_adm = [0 for _ in range(N)]

    def get_num_past_admissions(df):
        subject_id = df.iloc[0]['subject_id']
        if subject_id in grouped_adm.groups.keys():
            df_adm = grouped_adm.get_group(subject_id)
            start = end = df_adm.index[0]
            for i in df.index:
                if i % 10000 == 0:
                    print('Process: %d/%d' % (i, N), end='\r')
                while start < df_adm.index[-1] and df.loc[i, 'intime'] - df_adm.loc[start, 'admittime'] > timerange_delta:
                    start += 1
                end = start
                while end <= df_adm.index[-1] and \
                        (timerange_delta >= (df.loc[i, 'intime'] - df_adm.loc[end, 'admittime']) > timedelta(days=0)):
                    end += 1
                n_adm[i] = end - start

    grouped = df_master.groupby('subject_id')
    grouped_adm = df_admissions_sorted.groupby('subject_id')
    grouped.apply(get_num_past_admissions)
    print('Process: %d/%d' % (N, N), end='\r')

    df_master.loc[:,''.join(['n_hosp_', str(timerange), "d"])] = n_adm

    return df_master


def generate_past_icu_visits(df_master, df_icustays, timerange):
    df_icustays_sorted = df_icustays[df_icustays['subject_id'].isin(df_master['subject_id'].unique().tolist())][['subject_id', 'intime']].copy()
    df_icustays_sorted.sort_values(['subject_id', 'intime'], inplace=True)
    df_icustays_sorted.reset_index(drop=True, inplace=True)

    timerange_delta = timedelta(days=timerange)
    N = len(df_master)
    n_icu = [0 for _ in range(N)]
    def get_num_past_icu_visits(df):
        subject_id = df.iloc[0]['subject_id']
        if subject_id in grouped_icu.groups.keys():
            df_icu = grouped_icu.get_group(subject_id)
            start = end = df_icu.index[0]
            for i in df.index:
                if i % 10000 == 0:
                    print('Process: %d/%d' % (i, N), end='\r')
                while start < df_icu.index[-1] and df.loc[i, 'intime'] - df_icu.loc[start, 'intime'] > timerange_delta:
                    start += 1
                end = start
                while end <= df_icu.index[-1] and \
                        (timerange_delta >= (df.loc[i, 'intime'] - df_icu.loc[end, 'intime']) > timedelta(days=0)):
                    end += 1
                n_icu[i] = end - start

    grouped = df_master.groupby('subject_id')
    grouped_icu = df_icustays_sorted.groupby('subject_id')
    grouped.apply(get_num_past_icu_visits)
    print('Process: %d/%d' % (N, N), end='\r')

    df_master.loc[:,''.join(['n_icu_', str(timerange), "d"])] = n_icu

    return df_master


def generate_future_ed_visits(df_master, next_ed_visit_timerange):
    N = len(df_master)
    time_of_next_ed_visit = [float("NaN") for _ in range(N)]
    time_to_next_ed_visit = [float("NaN") for _ in range(N)]
    outcome_ed_revisit = [False for _ in range(N)]

    timerange_delta = timedelta(days = next_ed_visit_timerange)

    curr_subject=None
    next_subject=None

    def get_future_ed_visits(row):
        i = row.name
        if i % 10000 == 0:
            print('Process: %d/%d' % (i, N), end='\r')
        curr_subject = row['subject_id']
        next_subject= df_master['subject_id'][i+1] if i< (N-1) else None

        if curr_subject == next_subject:
            curr_outtime = row['outtime']
            next_intime = df_master['intime'][i+1]
            next_intime_diff = next_intime - curr_outtime

            time_of_next_ed_visit[i] = next_intime
            time_to_next_ed_visit[i] = next_intime_diff
            outcome_ed_revisit[i] = next_intime_diff < timerange_delta

    df_master.apply(get_future_ed_visits, axis=1)
    print('Process: %d/%d' % (N, N), end='\r')

    df_master.loc[:,'next_ed_visit_time'] = time_of_next_ed_visit
    df_master.loc[:,'next_ed_visit_time_diff'] = time_to_next_ed_visit
    df_master.loc[:,''.join(['outcome_ed_revisit_', str(next_ed_visit_timerange), "d"])] = outcome_ed_revisit

    return df_master


def generate_numeric_timedelta(df_master):
    N = len(df_master)
    ed_los_hours = [float("NaN") for _ in range(N)]
    time_to_icu_transfer_hours = [float("NaN") for _ in range(N)]
    next_ed_visit_time_diff_days = [float("NaN") for _ in range(N)]
    
    def get_numeric_timedelta(row):
        i = row.name
        if i % 10000 == 0:
            print('Process: %d/%d' % (i, N), end='\r')
        curr_subject = row['subject_id']
        curr_ed_los = row['ed_los']
        curr_time_to_icu_transfer = row['time_to_icu_transfer']
        curr_next_ed_visit_time_diff = row['next_ed_visit_time_diff']
        

        ed_los_hours[i] = round(curr_ed_los.total_seconds() / (60*60),2) if not pd.isna(curr_ed_los) else curr_ed_los
        time_to_icu_transfer_hours[i] = round(curr_time_to_icu_transfer.total_seconds() / (60*60),2) if not pd.isna(curr_time_to_icu_transfer) else curr_time_to_icu_transfer
        next_ed_visit_time_diff_days[i] = round(curr_next_ed_visit_time_diff.total_seconds() / (24*60*60), 2) if not pd.isna(curr_next_ed_visit_time_diff) else curr_next_ed_visit_time_diff
    

    df_master.apply(get_numeric_timedelta, axis=1)
    print('Process: %d/%d' % (N, N), end='\r')
    
    df_master.loc[:,'ed_los_hours'] = ed_los_hours
    df_master.loc[:,'time_to_icu_transfer_hours'] = time_to_icu_transfer_hours
    df_master.loc[:,'next_ed_visit_time_diff_days'] = next_ed_visit_time_diff_days

    return df_master


def encode_chief_complaints(df_master, complaint_dict):

    holder_list = []
    complaint_colnames_list = list(complaint_dict.keys())
    complaint_regex_list = list(complaint_dict.values())

    for i, row in df_master.iterrows():
        curr_patient_complaint = str(row['chiefcomplaint'])
        curr_patient_complaint_list = [False for _ in range(len(complaint_regex_list))]
        complaint_idx = 0

        for complaint in complaint_regex_list:
            if re.search(complaint, curr_patient_complaint, re.IGNORECASE):
                curr_patient_complaint_list[complaint_idx] = True
            complaint_idx += 1
        
        holder_list.append(curr_patient_complaint_list)
    
    df_encoded_complaint = pd.DataFrame(holder_list, columns = complaint_colnames_list)

    df_master = pd.concat([df_master,df_encoded_complaint], axis=1)
    return df_master

def merge_vitalsign_info_on_edstay(df_master, df_vitalsign, options=[]):
    df_vitalsign.sort_values('charttime', inplace=True)

    grouped = df_vitalsign.groupby(['stay_id'])

    for option in options:
        method = getattr(grouped, option, None)
        assert method is not None, "Invalid option. " \
                                   "Should be a list of values from 'max', 'min', 'median', 'mean', 'first', 'last'. " \
                                   "e.g. ['median', 'last']"
        df_vitalsign_option = method(numeric_only=True)
        df_vitalsign_option.rename({name: '_'.join([name, option]) for name in
                                    ['ed_temperature', 'ed_heartrate', 'ed_resprate', 'ed_o2sat', 'ed_sbp', 'ed_dbp', 'ed_pain']},
                                   axis=1,
                                   inplace=True)
        df_master = pd.merge(df_master, df_vitalsign_option, on=['subject_id', 'stay_id'], how='left')

    return df_master

def merge_med_count_on_edstay(df_master, df_pyxis):
    df_pyxis_fillna = df_pyxis.copy()
    df_pyxis_fillna['gsn'].fillna(df_pyxis['name'], inplace=True)
    grouped = df_pyxis_fillna.groupby(['stay_id'])
    df_medcount = grouped['gsn'].nunique().reset_index().rename({'gsn': 'n_med'}, axis=1)
    df_master = pd.merge(df_master, df_medcount, on='stay_id', how='left')
    df_master.fillna({'n_med': 0}, inplace=True)
    return df_master

def merge_medrecon_count_on_edstay(df_master, df_medrecon):
    df_medrecon_fillna = df_medrecon.copy()
    df_medrecon_fillna['gsn'].fillna(df_medrecon['name'])
    grouped = df_medrecon_fillna.groupby(['stay_id'])
    df_medcount = grouped['gsn'].nunique().reset_index().rename({'gsn': 'n_medrecon'}, axis=1)
    df_master = pd.merge(df_master, df_medcount, on='stay_id', how='left')
    df_master.fillna({'n_medrecon': 0}, inplace=True)
    return df_master

def outlier_removal_imputation(column_type, vitals_valid_range):
    column_range = vitals_valid_range[column_type]
    def outlier_removal_imputation_single_value(x):
        if x < column_range['outlier_low'] or x > column_range['outlier_high']:
            # set as missing
            return np.nan
        elif x < column_range['valid_low']:
            # impute with nearest valid value
            return column_range['valid_low']
        elif x > column_range['valid_high']:
            # impute with nearest valid value
            return column_range['valid_high']
        else:
            return x
    return outlier_removal_imputation_single_value

def convert_temp_to_celcius(df_master):
    for column in df_master.columns:
        column_type = column.split('_')[1] if len(column.split('_')) > 1 else None
        if column_type == 'temperature':
            # convert to celcius
            df_master[column] -= 32
            df_master[column] *= 5/9
    return df_master

def remove_outliers(df_master, vitals_valid_range):
    for column in df_master.columns:
        column_type = column.split('_')[1] if len(column.split('_')) > 1 else None
        if column_type in vitals_valid_range:
            df_master[column] = df_master[column].apply(outlier_removal_imputation(column_type, vitals_valid_range))
    return df_master

def display_outliers_count(df_master, vitals_valid_range):
    display_df = pd.DataFrame(columns=['variable', '< outlier_low', '[outlier_low, valid_low)',
                                       '[valid_low, valid_high]', '(valid_high, outlier_high]', '> outlier_high'])
    display_df.reset_index(drop=True, inplace=True)
    for column in df_master.columns:
        column_type = column.split('_')[1] if len(column.split('_')) > 1 else None
        if column_type in vitals_valid_range:
            column_range = vitals_valid_range[column_type]
            display_df = display_df.append({'variable': column,
                   '< outlier_low': len(df_master[df_master[column] < column_range['outlier_low']]),
                   '[outlier_low, valid_low)': len(df_master[(column_range['outlier_low'] <= df_master[column])
                                                             & (df_master[column] < column_range['valid_low'])]),
                   '[valid_low, valid_high]': len(df_master[(column_range['valid_low'] <= df_master[column])
                                                            & (df_master[column] <= column_range['valid_high'])]),
                   '(valid_high, outlier_high]': len(df_master[(column_range['valid_high'] < df_master[column])
                                                               & (df_master[column] <= column_range['outlier_high'])]),
                   '> outlier_high': len(df_master[df_master[column] > column_range['outlier_high']])
            }, ignore_index=True)
    return display_df

def display_outliers_count_new(df_master, vitals_valid_range):
    display_list = []

    for column in df_master.columns:
        column_type = column.split('_')[1] if len(column.split('_')) > 1 else None
        if column_type in vitals_valid_range:
            column_range = vitals_valid_range[column_type]
            display_list.append({
                'variable': column,
                '< outlier_low': len(df_master[df_master[column] < column_range['outlier_low']]),
                '[outlier_low, valid_low)': len(df_master[(column_range['outlier_low'] <= df_master[column])
                                                          & (df_master[column] < column_range['valid_low'])]),
                '[valid_low, valid_high]': len(df_master[(column_range['valid_low'] <= df_master[column])
                                                         & (df_master[column] <= column_range['valid_high'])]),
                '(valid_high, outlier_high]': len(df_master[(column_range['valid_high'] < df_master[column])
                                                            & (df_master[column] <= column_range['outlier_high'])]),
                '> outlier_high': len(df_master[df_master[column] > column_range['outlier_high']])
            })

    # Create a DataFrame from the list of dictionaries
    display_df = pd.DataFrame(display_list)
    return display_df

def add_score_CCI(df):
    conditions = [
        (df['age'] < 50),
        (df['age'] >= 50) & (df['age'] <= 59),
        (df['age'] >= 60) & (df['age'] <= 69),
        (df['age'] >= 70) & (df['age'] <= 79),
        (df['age'] >= 80)
    ]
    values = [0, 1, 2, 3, 4]
    df['score_CCI'] = np.select(conditions, values)    
    df['score_CCI'] = df['score_CCI'] + df['cci_MI'] + df['cci_CHF'] + df['cci_PVD'] + df['cci_Stroke'] + df['cci_Dementia'] + df['cci_Pulmonary'] + df['cci_PUD'] + df['cci_Rheumatic'] +df['cci_Liver1']*1 + df['cci_Liver2']*3 + df['cci_DM1'] + df['cci_DM2']*2 +df['cci_Paralysis']*2 + df['cci_Renal']*2 + df['cci_Cancer1']*2 + df['cci_Cancer2']*6 + df['cci_HIV']*6
    print("Variable 'add_score_CCI' successfully added")

def add_triage_MAP(df):
    df['triage_MAP'] = df['triage_sbp']*1/3 + df['triage_dbp']*2/3
    print("Variable 'add_triage_MAP' successfully added")

def add_score_REMS(df):
    conditions1 = [
        (df['age'] < 45),
        (df['age'] >= 45) & (df['age'] <= 54),
        (df['age'] >= 55) & (df['age'] <= 64),
        (df['age'] >= 65) & (df['age'] <= 74),
        (df['age'] > 74)
    ]
    values1 = [0, 2, 3, 5, 6]
    conditions2 = [
        (df['triage_MAP'] > 159),
        (df['triage_MAP'] >= 130) & (df['triage_MAP'] <= 159),
        (df['triage_MAP'] >= 110) & (df['triage_MAP'] <= 129),
        (df['triage_MAP'] >= 70) & (df['triage_MAP'] <= 109),
        (df['triage_MAP'] >= 50) & (df['triage_MAP'] <= 69),
        (df['triage_MAP'] < 49)
    ]
    values2 = [4, 3, 2, 0, 2, 4]
    conditions3 = [
        (df['triage_heartrate'] >179),
        (df['triage_heartrate'] >= 140) & (df['triage_heartrate'] <= 179),
        (df['triage_heartrate'] >= 110) & (df['triage_heartrate'] <= 139),
        (df['triage_heartrate'] >= 70) & (df['triage_heartrate'] <= 109),
        (df['triage_heartrate'] >= 55) & (df['triage_heartrate'] <= 69),
        (df['triage_heartrate'] >= 40) & (df['triage_heartrate'] <= 54),
        (df['triage_heartrate'] < 40)
    ]
    values3 = [4, 3, 2, 0, 2, 3, 4]
    conditions4 = [
        (df['triage_resprate'] > 49),
        (df['triage_resprate'] >= 35) & (df['triage_resprate'] <= 49),
        (df['triage_resprate'] >= 25) & (df['triage_resprate'] <= 34),
        (df['triage_resprate'] >= 12) & (df['triage_resprate'] <= 24),
        (df['triage_resprate'] >= 10) & (df['triage_resprate'] <= 11),
        (df['triage_resprate'] >= 6) & (df['triage_resprate'] <= 9),
        (df['triage_resprate'] < 6)
    ]
    values4 = [4, 3, 1, 0, 1, 2, 4]
    conditions5 = [
        (df['triage_o2sat'] < 75),
        (df['triage_o2sat'] >= 75) & (df['triage_o2sat'] <= 85),
        (df['triage_o2sat'] >= 86) & (df['triage_o2sat'] <= 89),
        (df['triage_o2sat'] > 89)
    ]
    values5 = [4, 3, 1, 0]
    df['score_REMS'] = np.select(conditions1, values1) + np.select(conditions2, values2) + np.select(conditions3, values3) +                              np.select(conditions4, values4) + np.select(conditions5, values5)
    print("Variable 'Score_REMS' successfully added")
    
def add_score_CART(df):
    conditions1 = [
        (df['age'] < 55),
        (df['age'] >= 55) & (df['age'] <= 69),
        (df['age'] >= 70) 
    ]
    values1 = [0, 4, 9]
    conditions2 = [
        (df['triage_resprate'] < 21),
        (df['triage_resprate'] >= 21) & (df['triage_resprate'] <= 23),
        (df['triage_resprate'] >= 24) & (df['triage_resprate'] <= 25),
        (df['triage_resprate'] >= 26) & (df['triage_resprate'] <= 29),
        (df['triage_resprate'] >= 30) 
    ]
    values2 = [0, 8, 12, 15, 22]
    conditions3 = [
        (df['triage_heartrate'] < 110),
        (df['triage_heartrate'] >= 110) & (df['triage_heartrate'] <= 139),
        (df['triage_heartrate'] >= 140) 
    ]
    values3 = [0, 4, 13]
    conditions4 = [
        (df['triage_dbp'] > 49),
        (df['triage_dbp'] >= 40) & (df['triage_dbp'] <= 49),
        (df['triage_dbp'] >= 35) & (df['triage_dbp'] <= 39),
        (df['triage_dbp'] < 35) 
    ]
    values4 = [0, 4, 6, 13]
    df['score_CART'] = np.select(conditions1, values1) + np.select(conditions2, values2) + np.select(conditions3, values3) +                              np.select(conditions4, values4)
    print("Variable 'Score_CART' successfully added")
    
def add_score_NEWS(df):
    conditions1 = [
        (df['triage_resprate'] <= 8),
        (df['triage_resprate'] >= 9) & (df['triage_resprate'] <= 11),
        (df['triage_resprate'] >= 12) & (df['triage_resprate'] <= 20),
        (df['triage_resprate'] >= 21) & (df['triage_resprate'] <= 24),
        (df['triage_resprate'] >= 25) 
    ]
    values1 = [3, 1, 0, 2, 3]
    conditions2 = [
        (df['triage_o2sat'] <= 91),
        (df['triage_o2sat'] >= 92) & (df['triage_o2sat'] <= 93),
        (df['triage_o2sat'] >= 94) & (df['triage_o2sat'] <= 95),
        (df['triage_o2sat'] >= 96) 
    ]
    values2 = [3, 2, 1, 0]
    conditions3 = [
        (df['triage_temperature'] <= 35),
        (df['triage_temperature'] > 35) & (df['triage_temperature'] <= 36),
        (df['triage_temperature'] > 36) & (df['triage_temperature'] <= 38),
        (df['triage_temperature'] > 38) & (df['triage_temperature'] <= 39),
        (df['triage_temperature'] > 39) 
    ]
    values3 = [3, 1, 0, 1, 2]
    conditions4 = [
        (df['triage_sbp'] <= 90),
        (df['triage_sbp'] >= 91) & (df['triage_sbp'] <= 100),
        (df['triage_sbp'] >= 101) & (df['triage_sbp'] <= 110),
        (df['triage_sbp'] >= 111) & (df['triage_sbp'] <= 219),
        (df['triage_sbp'] > 219) 
    ]
    values4 = [3, 2, 1, 0, 3]
    conditions5 = [
        (df['triage_heartrate'] <= 40),
        (df['triage_heartrate'] >= 41) & (df['triage_heartrate'] <= 50),
        (df['triage_heartrate'] >= 51) & (df['triage_heartrate'] <= 90),
        (df['triage_heartrate'] >= 91) & (df['triage_heartrate'] <= 110),
        (df['triage_heartrate'] >= 111) & (df['triage_heartrate'] <= 130),
        (df['triage_heartrate'] > 130) 
    ]
    values5 = [3, 1, 0, 1, 2, 3]    
    df['score_NEWS'] = np.select(conditions1, values1) + np.select(conditions2, values2) + np.select(conditions3, values3) +                              np.select(conditions4, values4) + np.select(conditions5, values5)
    print("Variable 'Score_NEWS' successfully added")
    
def add_score_NEWS2(df):   
    conditions1 = [
        (df['triage_resprate'] <= 8),
        (df['triage_resprate'] >= 9) & (df['triage_resprate'] <= 11),
        (df['triage_resprate'] >= 12) & (df['triage_resprate'] <= 20),
        (df['triage_resprate'] >= 21) & (df['triage_resprate'] <= 24),
        (df['triage_resprate'] >= 25) 
    ]
    values1 = [3, 1, 0, 2, 3]
    conditions2 = [
        (df['triage_temperature'] <= 35),
        (df['triage_temperature'] > 35) & (df['triage_temperature'] <= 36),
        (df['triage_temperature'] > 36) & (df['triage_temperature'] <= 38),
        (df['triage_temperature'] > 38) & (df['triage_temperature'] <= 39),
        (df['triage_temperature'] > 39) 
    ]
    values2 = [3, 1, 0, 1, 2]
    conditions3 = [
        (df['triage_sbp'] <= 90),
        (df['triage_sbp'] >= 91) & (df['triage_sbp'] <= 100),
        (df['triage_sbp'] >= 101) & (df['triage_sbp'] <= 110),
        (df['triage_sbp'] >= 111) & (df['triage_sbp'] <= 219),
        (df['triage_sbp'] > 219) 
    ]
    values3 = [3, 2, 1, 0, 3]
    conditions4 = [
        (df['triage_heartrate'] <= 40),
        (df['triage_heartrate'] >= 41) & (df['triage_heartrate'] <= 50),
        (df['triage_heartrate'] >= 51) & (df['triage_heartrate'] <= 90),
        (df['triage_heartrate'] >= 91) & (df['triage_heartrate'] <= 110),
        (df['triage_heartrate'] >= 111) & (df['triage_heartrate'] <= 130),
        (df['triage_heartrate'] > 130) 
    ]
    values4 = [3, 1, 0, 1, 2, 3]   
    df['score_NEWS2'] = np.select(conditions1, values1) + np.select(conditions2, values2) + np.select(conditions3, values3) +                              np.select(conditions4, values4)
    print("Variable 'Score_NEWS2' successfully added")
    
def add_score_MEWS(df):     
    conditions1 = [
        (df['triage_sbp'] <= 70),
        (df['triage_sbp'] >= 71) & (df['triage_sbp'] <= 80),
        (df['triage_sbp'] >= 81) & (df['triage_sbp'] <= 100),
        (df['triage_sbp'] >= 101) & (df['triage_sbp'] <= 199),
        (df['triage_sbp'] > 199) 
    ]
    values1 = [3, 2, 1, 0, 2]
    conditions2 = [
        (df['triage_heartrate'] <= 40),
        (df['triage_heartrate'] >= 41) & (df['triage_heartrate'] <= 50),
        (df['triage_heartrate'] >= 51) & (df['triage_heartrate'] <= 100),
        (df['triage_heartrate'] >= 101) & (df['triage_heartrate'] <= 110),
        (df['triage_heartrate'] >= 111) & (df['triage_heartrate'] <= 129),
        (df['triage_heartrate'] >= 130) 
    ]
    values2 = [2, 1, 0, 1, 2, 3]
    conditions3 = [
        (df['triage_resprate'] < 9),
        (df['triage_resprate'] >= 9) & (df['triage_resprate'] <= 14),
        (df['triage_resprate'] >= 15) & (df['triage_resprate'] <= 20),
        (df['triage_resprate'] >= 21) & (df['triage_resprate'] <= 29),
        (df['triage_resprate'] >= 30) 
    ]
    values3 = [2, 0, 1, 2, 3]
    conditions4 = [
        (df['triage_temperature'] < 35),
        (df['triage_temperature'] >= 35) & (df['triage_temperature'] < 38.5),
        (df['triage_temperature'] >= 38.5) 
    ]
    values4 = [2, 0, 2]        
    df['score_MEWS'] = np.select(conditions1, values1) + np.select(conditions2, values2) + np.select(conditions3, values3) +                              np.select(conditions4, values4) 
    print("Variable 'Score_MEWS' successfully added")
    
def add_score_SERP2d(df): 
    conditions1 = [
        (df['age'] < 30),
        (df['age'] >= 30) & (df['age'] <= 49),
        (df['age'] >= 50) & (df['age'] <= 79),
        (df['age'] >= 80)
    ]
    values1 = [0, 9, 13, 17]
    conditions2 = [
        (df['triage_heartrate'] < 60),
        (df['triage_heartrate'] >= 60) & (df['triage_heartrate'] <= 69),
        (df['triage_heartrate'] >= 70) & (df['triage_heartrate'] <= 94),
        (df['triage_heartrate'] >= 95) & (df['triage_heartrate'] <= 109),
        (df['triage_heartrate'] >= 110) 
    ]
    values2 = [3, 0, 3, 6, 10]
    conditions3 = [
        (df['triage_resprate'] < 16),
        (df['triage_resprate'] >= 16) & (df['triage_resprate'] <= 19),
        (df['triage_resprate'] >= 20) 
    ]
    values3 = [11, 0, 7]
    conditions4 = [
        (df['triage_sbp'] < 100),
        (df['triage_sbp'] >= 100) & (df['triage_sbp'] <= 114),
        (df['triage_sbp'] >= 115) & (df['triage_sbp'] <= 149),
        (df['triage_sbp'] >= 150) 
    ]
    values4 = [10, 4, 1, 0]
    conditions5 = [
        (df['triage_dbp'] < 50),
        (df['triage_dbp'] >= 50) & (df['triage_dbp'] <= 94),
        (df['triage_dbp'] >= 95) 
    ]
    values5 = [5, 0, 1]
    conditions6 = [
        (df['triage_o2sat'] < 90),
        (df['triage_o2sat'] >= 90) & (df['triage_o2sat'] <= 94),
        (df['triage_o2sat'] >= 95) 
    ]
    values6 = [7, 5, 0]
    df['score_SERP2d'] = np.select(conditions1, values1) + np.select(conditions2, values2) + np.select(conditions3, values3) +                              np.select(conditions4, values4) + np.select(conditions5, values5) + np.select(conditions6, values6)
    print("Variable 'Score_SERP2d' successfully added")

def add_score_SERP7d(df): 
    conditions1 = [
        (df['age'] < 30),
        (df['age'] >= 30) & (df['age'] <= 49),
        (df['age'] >= 50) & (df['age'] <= 79),
        (df['age'] >= 80)
    ]
    values1 = [0, 10, 17, 21]
    conditions2 = [
        (df['triage_heartrate'] < 60),
        (df['triage_heartrate'] >= 60) & (df['triage_heartrate'] <= 69),
        (df['triage_heartrate'] >= 70) & (df['triage_heartrate'] <= 94),
        (df['triage_heartrate'] >= 95) & (df['triage_heartrate'] <= 109),
        (df['triage_heartrate'] >= 110) 
    ]
    values2 = [2, 0, 4, 8, 12]
    conditions3 = [
        (df['triage_resprate'] < 16),
        (df['triage_resprate'] >= 16) & (df['triage_resprate'] <= 19),
        (df['triage_resprate'] >= 20) 
    ]
    values3 = [10, 0, 6]
    conditions4 = [
        (df['triage_sbp'] < 100),
        (df['triage_sbp'] >= 100) & (df['triage_sbp'] <= 114),
        (df['triage_sbp'] >= 115) & (df['triage_sbp'] <= 149),
        (df['triage_sbp'] >= 150) 
    ]
    values4 = [12, 6, 1, 0]
    conditions5 = [
        (df['triage_dbp'] < 50),
        (df['triage_dbp'] >= 50) & (df['triage_dbp'] <= 94),
        (df['triage_dbp'] >= 95) 
    ]
    values5 = [4, 0, 2]
    df['score_SERP7d'] = np.select(conditions1, values1) + np.select(conditions2, values2) + np.select(conditions3, values3) +                              np.select(conditions4, values4) + np.select(conditions5, values5)
    print("Variable 'Score_SERP7d' successfully added")
    
def add_score_SERP30d(df): 
    conditions1 = [
        (df['age'] < 30),
        (df['age'] >= 30) & (df['age'] <= 49),
        (df['age'] >= 50) & (df['age'] <= 79),
        (df['age'] >= 80)
    ]
    values1 = [0, 8, 14, 19]
    conditions2 = [
        (df['triage_heartrate'] < 60),
        (df['triage_heartrate'] >= 60) & (df['triage_heartrate'] <= 69),
        (df['triage_heartrate'] >= 70) & (df['triage_heartrate'] <= 94),
        (df['triage_heartrate'] >= 95) & (df['triage_heartrate'] <= 109),
        (df['triage_heartrate'] >= 110) 
    ]
    values2 = [1, 0, 2, 6, 9]
    conditions3 = [
        (df['triage_resprate'] < 16),
        (df['triage_resprate'] >= 16) & (df['triage_resprate'] <= 19),
        (df['triage_resprate'] >= 20) 
    ]
    values3 = [8, 0, 6]
    conditions4 = [
        (df['triage_sbp'] < 100),
        (df['triage_sbp'] >= 100) & (df['triage_sbp'] <= 114),
        (df['triage_sbp'] >= 115) & (df['triage_sbp'] <= 149),
        (df['triage_sbp'] >= 150) 
    ]
    values4 = [8, 5, 2, 0]
    conditions5 = [
        (df['triage_dbp'] < 50),
        (df['triage_dbp'] >= 50) & (df['triage_dbp'] <= 94),
        (df['triage_dbp'] >= 95) 
    ]
    values5 = [3, 0, 2]
    df['score_SERP30d'] = np.select(conditions1, values1) + np.select(conditions2, values2) + np.select(conditions3, values3) +                              np.select(conditions4, values4) + np.select(conditions5, values5) + df['cci_Cancer1']*6 + df['cci_Cancer2']*12
    print("Variable 'Score_SERP30d' successfully added")
def PlotROCCurveNew(probs,y_test_roc, ci= 95, random_seed=0):
    
    fpr, tpr, threshold = sklearn_roc_curve(y_test_roc,probs)
    roc_auc = roc_auc_score(y_test_roc, probs)
    average_precision = average_precision_score(y_test_roc, probs)
    a=np.sqrt(np.square(fpr-0)+np.square(tpr-1)).argmin()
    sensitivity = tpr[a]
    specificity = 1-fpr[a]
    threshold = threshold[a]
    print("AUC:",roc_auc)
    print("AUPRC:", average_precision)
    print("Sensitivity:",sensitivity)
    print("Specificity:",specificity)
    print("Score thresold:",threshold)
    lower_auroc, upper_auroc, std_auroc, lower_ap, upper_ap, std_ap, lower_sensitivity, upper_sensitivity, std_sensitivity, lower_specificity, upper_specificity, std_specificity = cuc_with_ci(probs,y_test_roc, lower = (100-ci)/2, upper = 100-(100-ci)/2, n_bootstraps=20, rng_seed=random_seed)
    
    plt.title('Receiver Operating Characteristic: AUC={0:0.4f}'.format(
          roc_auc))
    plt.plot(fpr, tpr, 'b')
    plt.plot([0, 1], [0, 1],'r--')
    plt.xlim([0, 1])
    plt.ylim([0, 1])
    plt.ylabel('True Positive Rate')
    plt.xlabel('False Positive Rate')
    plt.show()

    precision, recall, threshold2 = precision_recall_curve(y_test_roc, probs)
    plt.step(recall, precision, color='b', alpha=0.2,
         where='post')
    plt.fill_between(recall, precision, step='post', alpha=0.2,
                 color='b')
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.ylim([0.0, 1.05])
    plt.xlim([0.0, 1.0])
    plt.title('Precision-Recall Curve: AUPRC={0:0.4f}'.format(
          average_precision))
    plt.show()
    return [roc_auc, average_precision, sensitivity, specificity, threshold, lower_auroc, upper_auroc, std_auroc, lower_ap, upper_ap, std_ap, lower_sensitivity, upper_sensitivity, std_sensitivity, lower_specificity, upper_specificity, std_specificity]
    
    
def PlotROCCurve(probs,y_test_roc, ci= 95, random_seed=0):
    
    fpr, tpr, threshold = metrics.roc_curve(y_test_roc,probs)
    roc_auc = metrics.auc(fpr, tpr)
    average_precision = average_precision_score(y_test_roc, probs)
    a=np.sqrt(np.square(fpr-0)+np.square(tpr-1)).argmin()
    sensitivity = tpr[a]
    specificity = 1-fpr[a]
    threshold = threshold[a]
    print("AUC:",roc_auc)
    print("AUPRC:", average_precision)
    print("Sensitivity:",sensitivity)
    print("Specificity:",specificity)
    print("Score thresold:",threshold)
    lower_auroc, upper_auroc, std_auroc, lower_ap, upper_ap, std_ap, lower_sensitivity, upper_sensitivity, std_sensitivity, lower_specificity, upper_specificity, std_specificity = auc_with_ci(probs,y_test_roc, lower = (100-ci)/2, upper = 100-(100-ci)/2, n_bootstraps=20, rng_seed=random_seed)


    plt.title('Receiver Operating Characteristic: AUC={0:0.4f}'.format(
          roc_auc))
    plt.plot(fpr, tpr, 'b')
    plt.plot([0, 1], [0, 1],'r--')
    plt.xlim([0, 1])
    plt.ylim([0, 1])
    plt.ylabel('True Positive Rate')
    plt.xlabel('False Positive Rate')
    plt.show()

    precision, recall, threshold2 = precision_recall_curve(y_test_roc, probs)
    plt.step(recall, precision, color='b', alpha=0.2,
         where='post')
    plt.fill_between(recall, precision, step='post', alpha=0.2,
                 color='b')
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.ylim([0.0, 1.05])
    plt.xlim([0.0, 1.0])
    plt.title('Precision-Recall Curve: AUPRC={0:0.4f}'.format(
          average_precision))
    plt.show()
    return [roc_auc, average_precision, sensitivity, specificity, threshold, lower_auroc, upper_auroc, std_auroc, lower_ap, upper_ap, std_ap, lower_sensitivity, upper_sensitivity, std_sensitivity, lower_specificity, upper_specificity, std_specificity]

def cuc_with_ci(probs,y_test_roc, lower = 2.5, upper = 97.5, n_bootstraps=200, rng_seed=10):
    print(lower, upper)
    y_test_roc = np.asarray(y_test_roc)
    bootstrapped_auroc = []
    bootstrapped_ap = []
    bootstrapped_sensitivity = []
    bootstrapped_specificity = []
    result_dict = {}
    rng = np.random.default_rng(rng_seed)
    for i in range(n_bootstraps):
        # bootstrap by sampling with replacement on the prediction indices
        indices = rng.integers(0, len(y_test_roc)-1, len(y_test_roc))
        if len(np.unique(y_test_roc[indices])) < 2:
            # We need at least one positive and one negative sample for ROC AUC
            # to be defined: reject the sample
            continue
        fpr, tpr, threshold = sklearn_roc_curve(y_test_roc[indices], probs[indices])
        auroc = roc_auc_score(y_test_roc[indices], probs[indices])
        ap = average_precision_score(y_test_roc[indices], probs[indices])
        a=np.sqrt(np.square(fpr-0)+np.square(tpr-1)).argmin()
        sensitivity = tpr[a]
        specificity = 1-fpr[a]
        bootstrapped_auroc.append(auroc)
        bootstrapped_ap.append(ap)
        bootstrapped_sensitivity.append(sensitivity)
        bootstrapped_specificity.append(specificity)

    lower_auroc,upper_auroc = np.percentile(bootstrapped_auroc, [lower, upper])
    lower_ap,upper_ap = np.percentile(bootstrapped_ap, [lower, upper])
    lower_sensitivity,upper_sensitivity = np.percentile(bootstrapped_sensitivity, [lower, upper])
    lower_specificity,upper_specificity = np.percentile(bootstrapped_specificity, [lower, upper])

    std_auroc = np.std(bootstrapped_auroc)
    std_ap = np.std(bootstrapped_ap)
    std_sensitivity = np.std(bootstrapped_sensitivity)
    std_specificity = np.std(bootstrapped_specificity)
    result_dict = {
                            'AUROC': (auroc,lower_auroc, upper_auroc, std_auroc),
                            'AP': (ap,lower_ap, upper_ap, std_ap),
                            'Sensitivity': (sensitivity,lower_sensitivity, upper_sensitivity, std_sensitivity),
                            'Specificity': (specificity,lower_specificity, upper_specificity, std_specificity),
        }

    return lower_auroc, upper_auroc, std_auroc, lower_ap, upper_ap, std_ap, lower_sensitivity, upper_sensitivity, std_sensitivity, lower_specificity, upper_specificity, std_specificity


def auc_with_ci(probs,y_test_roc, lower = 2.5, upper = 97.5, n_bootstraps=200, rng_seed=10):
    print(lower, upper)
    y_test_roc = np.asarray(y_test_roc)
    bootstrapped_auroc = []
    bootstrapped_ap = []
    bootstrapped_sensitivity = []
    bootstrapped_specificity = []

    rng = np.random.default_rng(rng_seed)
    for i in range(n_bootstraps):
        # bootstrap by sampling with replacement on the prediction indices
        indices = rng.integers(0, len(y_test_roc)-1, len(y_test_roc))
        if len(np.unique(y_test_roc[indices])) < 2:
            # We need at least one positive and one negative sample for ROC AUC
            # to be defined: reject the sample
            continue
        fpr, tpr, threshold = metrics.roc_curve(y_test_roc[indices],probs[indices])
        auroc = metrics.auc(fpr, tpr)
        ap = metrics.average_precision_score(y_test_roc[indices], probs[indices])
        a=np.sqrt(np.square(fpr-0)+np.square(tpr-1)).argmin()
        sensitivity = tpr[a]
        specificity = 1-fpr[a]
        bootstrapped_auroc.append(auroc)
        bootstrapped_ap.append(ap)
        bootstrapped_sensitivity.append(sensitivity)
        bootstrapped_specificity.append(specificity)

    lower_auroc,upper_auroc = np.percentile(bootstrapped_auroc, [lower, upper])
    lower_ap,upper_ap = np.percentile(bootstrapped_ap, [lower, upper])
    lower_sensitivity,upper_sensitivity = np.percentile(bootstrapped_sensitivity, [lower, upper])
    lower_specificity,upper_specificity = np.percentile(bootstrapped_specificity, [lower, upper])

    std_auroc = np.std(bootstrapped_auroc)
    std_ap = np.std(bootstrapped_ap)
    std_sensitivity = np.std(bootstrapped_sensitivity)
    std_specificity = np.std(bootstrapped_specificity)

    return lower_auroc, upper_auroc, std_auroc, lower_ap, upper_ap, std_ap, lower_sensitivity, upper_sensitivity, std_sensitivity, lower_specificity, upper_specificity, std_specificity

def perform_10_fold_cv(X, y, random_seed=0):
    # Initialize Random Forest Classifier
    rf = RandomForestClassifier(random_state=random_seed)

    # Perform 10-fold cross-validation with multiple scoring metrics
    y_probas = cross_val_predict(rf, X, y, cv=StratifiedKFold(n_splits=10, shuffle=True, random_state=random_seed), method='predict_proba')

    return y_probas


def plot_confidence_interval(dataset, metric= 'auroc', ci=95, name = 'AUROC', my_file = 'AUROC_hosp.eps', my_path = 'my_path', dpi=300):
    ci_list = [dataset['lower_'+metric].values.tolist(),dataset['upper_'+metric].values.tolist()]
    std = [(dataset[metric]-dataset['std_'+metric]).values.tolist(), (dataset[metric]+dataset['std_'+metric]).values.tolist()]
    auc = dataset[metric].values.tolist()
    y = [range(len(dataset)), range(len(dataset))]

    plt.plot(ci_list,y, '-', color='gray',linewidth=1.5)
    plt.plot(std,y,'-', color='black', linewidth=2)
    plt.plot(auc,y[0],'|k', markersize=4)
    plt.xlabel(name)
    plt.yticks(range(len(dataset)),list(dataset['Model']))
    plt.savefig(os.path.join(my_path, my_file), format='eps', dpi=dpi)
    
    plt.show()


class LSTMDataGenerator(Sequence):
    def __init__(self, main_df, vitalsign_df, y, batch_size, x1_cols, x2_cols):
        self.main_df = main_df
        self.vitalsign_df = vitalsign_df
        self.batch_size = batch_size
        self.x1_cols = x1_cols
        self.x2_cols = x2_cols
        self.y_df = y

    def __len__(self):
        return math.ceil(len(self.main_df) / self.batch_size)

    def __getitem__(self, index):
        df_batch = self.main_df.iloc[index * self.batch_size:(index + 1) * self.batch_size]
        x1 = df_batch[self.x1_cols].to_numpy().astype(np.float64)
        y = self.y_df.iloc[index * self.batch_size:(index + 1) * self.batch_size].to_numpy()
        stay_ids = df_batch['stay_id'].to_numpy().astype(np.int64)
        batch_size = len(df_batch)
        df_batch = df_batch.merge(self.vitalsign_df, on='stay_id', how='left')
        x2 = []
        for i in range(batch_size):
            x2.append(df_batch[df_batch['stay_id'] == stay_ids[i]][self.x2_cols].to_numpy())
        padded_x2 = pad_sequences(x2, padding='post')
        return [x1, padded_x2.astype(np.float64)], y


def get_lstm_data_gen(df_train, df_test, df_vitalsign, variable, outcome, batch_size=200):
    variable_with_id = ["stay_id"]
    variable_with_id.extend(variable)

    X_train = df_train[variable_with_id].copy()
    y_train = df_train[outcome].copy()
    X_test = df_test[variable_with_id].copy()
    y_test = df_test[outcome].copy()

    if 'gender' in variable:
        encoder = LabelEncoder()
        X_train['gender'] = encoder.fit_transform(X_train['gender'])
        X_test['gender'] = encoder.transform(X_test['gender'])

    if 'ed_los' in variable:
        X_train['ed_los'] = pd.to_timedelta(X_train['ed_los']).dt.seconds / 60
        X_test['ed_los'] = pd.to_timedelta(X_test['ed_los']).dt.seconds / 60

    x1_cols = [x for x in variable_with_id[1:] if not ('ed' in x and 'last' in x)]
    x2_cols = [x for x in df_vitalsign.columns if 'ed' in x]

    train_data_gen = LSTMDataGenerator(X_train, df_vitalsign, y_train, batch_size, x1_cols, x2_cols)
    test_data_gen = LSTMDataGenerator(X_test, df_vitalsign, y_test, batch_size, x1_cols, x2_cols)

    return train_data_gen, test_data_gen
