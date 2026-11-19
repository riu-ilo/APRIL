#include <iostream>
using namespace std;

const int TIMEOUT = 60;
const int MAX_USERS = 100;
const int RETRY_COUNT = 5;
constexpr double TAX_RATE = 0.20;
     
int calculateScore(int marks) {
    return marks * 2;
}

int main() {
    cout << TIMEOUT << endl;
    return 0;
}