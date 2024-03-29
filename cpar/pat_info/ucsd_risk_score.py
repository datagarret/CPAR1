import pandas as pd
import sys
import os
import configparser
import itertools
import numpy as np
from CHECK.dbconnect import dbconnect


class RiskScore(object):

    def getCodesToReport(self, codes, recip):
        # The ICD9 codes and RecipientIDs will be passed as parameters to
        # getCodesToReport function
        recipCodeGroup = {i: {} for i in range(len(codes))}
        for i in range(len(codes)):
            recipCodeGroup[i]["Found"] = False
            recipCodeGroup[i]["IDsFound"] = []
        foundCount = 0

        for recipCodeIdx in range(len(codes)):
            codeInfo = codes[recipCodeIdx]
            # Contains the ICD9 & ICD10 codes that has been passed as a
            # parameter
            code = codeInfo[recipCodeIdx]
            # Loop through all Diagnostic Code Groups
            for cSetGroup in sorted(self.codeSet.keys()):
                # csValues contains all the categories of the codes from key 0
                # to key 18 (19 categories in total)
                csValues = self.codeSet[cSetGroup]
                foundIt = False
                # Check if the key "code" is in dictionary d1
                if code in self.d1:
                    # Contains the character diagnstic codes that corresponds
                    # to the numerical ICD9 codes
                    recipDiagCode = self.d1[code]
                else:
                    break
                if csValues.__contains__(recipDiagCode):
                    idIdx = self.codeSet[cSetGroup].index(recipDiagCode)
                    if idIdx >= 0:
                        foundIt = True
                        # recipCodeIdx --> position of the ICD codes, "Found"
                        # denotes whether the ICD code was found or not.
                        recipCodeGroup[recipCodeIdx]["Found"] = True
                        recipCodeGroup[recipCodeIdx]["IDsFound"].append([recipDiagCode, cSetGroup, idIdx])
                        # "IDsFound" denotes for the position in the
                        # codes.txt file
                        foundCount += 1
                        break
        retList = []
        # positions of the ICD codes
        for recipGroupID in recipCodeGroup.keys():
            if recipCodeGroup[recipGroupID]["Found"] is True:
                retList.append(recipCodeGroup[recipGroupID]["IDsFound"][0])
        return retList

    def execute_cursor(self, sql):
        df = self.connector.query(sql, df_flag=True)
        # for i in range(cursor.rowcount):
        for index, rows in df.iterrows():
            # row=cursor.fetchone()
            # d3 Dictionary will contain the recipValues
            # (ICD Codes) and recipID (RIN)
            d3 = {}
            for line in rows:
                fields = str(line).split("=")
                iD = fields.pop(0).strip("'")  # iD represents my RIN
                # Each array will contain all the ICD codes associated
                # with that patient
                d3[iD] = []
                fldNum = 0
                while fields:
                    d3[iD].append({fldNum: fields.pop(0).strip("'\n\r")})
                    fldNum += 1
                for recipID, recipValues in d3.items():
                    # Index 0 of each 3 item list is the Diagnostic Code for
                    # the Diag ID, index 1 is the Group index of the Diagnostic
                    # Code and index 2 is the relative index of
                    # the Diagnostic Code in the Diagnostic Group.
                    # print(repCodes)
                    repCodes = self.getCodesToReport(recipValues, recipID)
                    if len(repCodes) < 0:
                        print("""Error, Not all diagnostics codes found for the
                                 RecipientID; %s""" % recipID)
                    self.masterD[recipID] = repCodes

    def report_generator(self):
        for recipID in sorted(self.masterD.keys()):
            # codeDetailSets contains the Diagnosis code, category (0-18)
            # and relative index
            codeDetailSets = self.masterD[recipID]
            # masterDC[recipID]=masterD[recipID]
            reportStr = str(recipID)
            reportStr += "\t"
            addSpace = False
            for codeDef in codeDetailSets:
                if addSpace:
                    reportStr += " "
                reportStr += str(codeDef[0])
                addSpace = True  # TODO
            reportStr += '\t\t\t'
            lastCodeList = []
            groupsDone = []
            lastCodes = []

            while codeDetailSets:
                codeDef = codeDetailSets.pop(0)
                rcode = codeDef[0]
                grp = codeDef[1]
                grpIdx = codeDef[2]
                if not grp in groupsDone:
                    for laterCodeDef in codeDetailSets:
                        grp2 = laterCodeDef[1]
                        if grp2 == grp:
                            if laterCodeDef[2] < grpIdx:
                                rcode = laterCodeDef[0]
                                grpIdx = laterCodeDef[2]
                    reportStr += rcode + ','
                    lastCodes.append(rcode)
                groupsDone.append(grp)  # TODO
            reportStr = reportStr[:-1]
            yield [reportStr, lastCodes]

    def calculate_ucsd_risk(self):

        self.connector = dbconnect.DatabaseConnect('CHECK_CPAR2')
        dir = "/home/data_upload/.ipython/CHECK/cpar"
        file1 = open(dir + "/pat_info/ucsd_files/cdpsfmt1.child.txt", "r")
        self.d1 = {}
        for line in file1:
            x1 = line.split("=")
            key = x1[0].strip("'\r")
            value = x1[1].strip(';\n\r')
            self.d1[key] = value.strip("'")

        fd = open(dir + "/pat_info/ucsd_files/codes.txt", "r")
        self.codeSet = {}
        i = 0
        for line in fd:
            self.codeSet[i] = line.split()
            i += 1

        file3 = open(dir + "/pat_info/ucsd_files/cdps_dadc.txt", "r")
        d4 = {}
        for line in file3:
            x1 = line.split("=")
            key = x1[0].strip("'\r")
            value = x1[1].strip(';\n\r')
            d4[key] = value.strip()

        self.masterD = {}

        sql2 = """SELECT REPLACE(FILE,',',"'='") UCSD_RISK
                  FROM (SELECT CONCAT (hfsr.RecipientID,"='",hfsr.ICD_list,"'")
                  FILE FROM CHECK_CPAR2.pat_info_dx_primary  hfsr) tbl1"""

        self.execute_cursor(sql2)
        rGen = self.report_generator()
        info = next(rGen)
        risk_raw_df = pd.DataFrame(columns=['RecipientID', 'Risk'])
        i = 0
        while info:
            # print(info)
            lineToPrint = info[0][:]
            total = 0.0
            for item in info[1]:
                total = total + float(d4[item])
            lineToPrint += "\t\t" + str(total)
            RIN = lineToPrint[0:9]
            # print(RIN, total)
            risk_raw_df.loc[i, 'RecipientID'] = RIN
            risk_raw_df.loc[i, 'Risk'] = total

            i = i + 1
            try:
                info = next(rGen)
            except StopIteration:
                break

        demo_df = self.connector.query('''select RecipientID, Gender,
                                     Age from pat_info_demo;''')

        risk_raw_df = pd.merge(risk_raw_df, demo_df, on='RecipientID',
                               how='left')

        risk_raw_df.loc[(risk_raw_df['Age'] <= 1),
                        'RiskScore'] = risk_raw_df['Risk'] + 0.398 + 0.226
        risk_raw_df.loc[((risk_raw_df['Age'] > 1) & (risk_raw_df['Age'] < 5)),
                        'RiskScore'] = risk_raw_df['Risk'] - 0.068 + 0.226
        risk_raw_df.loc[((risk_raw_df['Age'] >= 5) & (risk_raw_df['Age'] < 15)
                        & (risk_raw_df['Gender'] == 'Male')),
                        'RiskScore'] = risk_raw_df['Risk'] - 0.06 + 0.226
        risk_raw_df.loc[((risk_raw_df['Age'] >= 5) & (risk_raw_df['Age'] < 15)
                        & (risk_raw_df['Gender'] == 'Female')),
                        'RiskScore'] = risk_raw_df['Risk'] - 0.105 + 0.226
        risk_raw_df.loc[((risk_raw_df['Age'] >= 15) & (risk_raw_df['Age'] < 25)
                        & (risk_raw_df['Gender'] == 'Male')),
                        'RiskScore'] = risk_raw_df['Risk'] - 0.026 + 0.226
        risk_raw_df.loc[((risk_raw_df['Age'] >= 15) & (risk_raw_df['Age'] < 25)
                        & (risk_raw_df['Gender'] == 'Female')),
                        'RiskScore'] = risk_raw_df['Risk'] + 0.051 + 0.226
        risk_raw_df.loc[((risk_raw_df['Age'] >= 25) &
                        (risk_raw_df['Gender'] == 'Male')),
                        'RiskScore'] = risk_raw_df['Risk'] - 0.068 + 0.226
        risk_raw_df.loc[((risk_raw_df['Age'] >= 25) &
                        (risk_raw_df['Gender'] == 'Female')),
                        'RiskScore'] = risk_raw_df['Risk'] + 0.041 + 0.226

        risk_raw_df = risk_raw_df.drop(['Gender', 'Age'], axis=1)

        risk_raw_df = risk_raw_df.rename(columns = {'Risk':'UCSD_Risk_Raw',
                                                    'RiskScore':'UCSD_Risk'})

        return risk_raw_df
