
#include <iostream>
#include <fstream>
#include "../include/constant_extractor.h"

int main() {
    std::ifstream oldFile("test_data/old.cpp");
    std::ifstream newFile("test_data/new.cpp");

    if (!oldFile.is_open() || !newFile.is_open()) {
        std::cerr << "Error: Could not open input files!" << std::endl;
        return 1;
    }

    oldFile.close();
    newFile.close();
 
    std::vector<Constant> oldConstants = extractConstants("test_data/old.cpp");
    std::vector<Constant> newConstants = extractConstants("test_data/new.cpp");
    std::vector<Change> changes = compareConstants(oldConstants, newConstants);

    generateJSON(changes);

    return 0;
}
