
#include <iostream>
#include <fstream>
#include <string>

using namespace std;

int main() {
    ifstream file("reader.txt");
    
    if (!file.is_open()) {
        cerr << "Error: Unable to open reader.txt!" << endl;
        return 1;
    }
    
    string line;
    while (getline(file, line)) {
        cout << line << endl;
    }
    
    file.close();
    return 0;
}
