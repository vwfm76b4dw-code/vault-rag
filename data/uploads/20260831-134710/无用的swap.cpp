#include<iostream>
using namespace std;
void swap(int a,int b)
{   int tem = a;
	a = b;
	b = tem;
}//摆设 
int main()
{   int a = 10;
	int b = 20;
	cout << "交换前" << endl;
	cout << "a=" << a << endl;
	cout << "b=" << b << endl;
	swap(a, b);
	cout << "交换后" << endl;
	cout << "a=" << a << endl;
	cout << "b=" << b << endl;
	return 0;
}

