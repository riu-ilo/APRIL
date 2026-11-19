#ifndef CONSTANT_EXTRACTOR_H
#define CONSTANT_EXTRACTOR_H

#include <string>
#include <vector>

struct Constant {
    std::string name;
    std::string type;
    std::string value;
    int lineNumber;
};

struct Change {
    std::string symbol;
    std::string oldValue;
    std::string newValue;
    std::string oldType;
    std::string newType;
    std::string changeType;
    int oldLine;
    int newLine;
};

std::vector<Constant> extractConstants(std::string filename);

std::vector<Change> compareConstants(
    const std::vector<Constant>& oldConstants,
    const std::vector<Constant>& newConstants
);

void generateJSON(const std::vector<Change>& changes);

#endif