
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <regex>

#include "../include/constant_extractor.h"
#include "../include/json.hpp"

using namespace std;
using json = nlohmann::json;

// vector<Constant> extractConstants(string filename) {
//     vector<Constant> constants;
//     ifstream file(filename);

//     if (!file.is_open()) {
//         cerr << "Could not open: " << filename << endl;
//         return constants;
//     }

//     string line;
//     int lineNumber = 0;

//     while (getline(file, line)) {
//         lineNumber++;

//         string keyword, type, identifier, assignment, value;
//         stringstream ss(line);

//         ss >> keyword >> type >> identifier >> assignment >> value;

//         if (keyword == "const" && assignment == "=") {
//             if (!value.empty() && value.back() == ';') {
//                 value.pop_back();
//             }

//             Constant c;
//             c.name = identifier;
//             c.type = type;
//             c.value = value;
//             c.lineNumber = lineNumber;

//             constants.push_back(c);
//         }
//     }

//     return constants;
// }

vector<Constant> extractConstants(string filename) {

    vector<Constant> constants;
    ifstream file(filename);

    if (!file.is_open()) {
        cerr << "Could not open: " << filename << endl;
        return constants;
    }

    regex constantPattern(
        R"(^\s*(const|constexpr)\s+(.+?)\s+([A-Za-z_]\w*)\s*=\s*(.*?)\s*;\s*(?://.*)?$)"
    );

    string line;
    int lineNumber = 0;

    while (getline(file, line)) {
        lineNumber++;

        smatch match;

        if (regex_match(line, match, constantPattern)) {

            Constant c;

            c.type = match[2].str();
            c.name = match[3].str();
            c.value = match[4].str();
            c.lineNumber = lineNumber;

            constants.push_back(c);
        }
    }

    return constants;
}


vector<Change> compareConstants(
    const vector<Constant>& oldConstants,
    const vector<Constant>& newConstants
) {
    vector<Change> changes;

    for (const Constant& oldC : oldConstants) {
        bool found = false;

        for (const Constant& newC : newConstants) {
            if (oldC.name == newC.name) {
                found = true;

                if (oldC.value != newC.value ||
                    oldC.type != newC.type) {

                    Change change;
                    change.symbol = oldC.name;
                    change.oldValue = oldC.value;
                    change.newValue = newC.value;
                    change.changeType = "modified";
                    change.oldLine = oldC.lineNumber;
                    change.newLine = newC.lineNumber;
                    change.oldType = oldC.type;
                    change.newType = newC.type;

                    changes.push_back(change);
                }

                break;
            }
        }

        if (!found) {
            Change change;
            change.symbol = oldC.name;
            change.oldValue = oldC.value;
            change.newValue = "";
            change.changeType = "removed";
            change.oldType = oldC.type;
            change.newType = "";
            change.oldLine = oldC.lineNumber;
            change.newLine = -1;

            changes.push_back(change);
        }
    }

    for (const Constant& newC : newConstants) {
        bool found = false;

        for (const Constant& oldC : oldConstants) {
            if (newC.name == oldC.name) {
                found = true;
                break;
            }
        }

        if (!found) {
            Change change;
            change.symbol = newC.name;
            change.oldValue = "";
            change.newValue = newC.value;
            change.changeType = "added";
            change.oldType = "";
            change.newType = newC.type;
            change.oldLine = -1;
            change.newLine = newC.lineNumber;

            changes.push_back(change);
        }
    }

    return changes;
}

void generateJSON(const vector<Change>& changes) {
    json report;

    report["language"] = "cpp";
    report["status"] = "success";
    report["total_changes"] = changes.size();

    report["summary"]["added"] = 0;
    report["summary"]["removed"] = 0;
    report["summary"]["modified"] = 0;

    report["changes"] = json::array();

    for (const Change& c : changes) {
        json item;
        if (c.changeType == "added") {
            report["summary"]["added"] = report["summary"]["added"].get<int>() + 1;
        }
        else if (c.changeType == "removed") {
            report["summary"]["removed"] = report["summary"]["removed"].get<int>() + 1;
        }
        else if (c.changeType == "modified") {
            report["summary"]["modified"] = report["summary"]["modified"].get<int>() + 1;
        }

        item["symbol"] = c.symbol;
        item["change_type"] = c.changeType;
        item["old_value"] = c.oldValue;
        item["new_value"] = c.newValue;
        item["old_type"] = c.oldType;
        item["new_type"] = c.newType;
        item["old_line"] = c.oldLine;
        item["new_line"] = c.newLine;

        report["changes"].push_back(item);
    }

    ofstream output("output/changes.json");

    if (!output.is_open()) {
        cerr << "Could not create JSON output!" << endl;
        return;
    }

    output << report.dump(4);
    output.close();

    cout << "JSON report generated successfully!" << endl;
}
